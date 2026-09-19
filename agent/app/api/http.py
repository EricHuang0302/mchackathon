from __future__ import annotations

import base64
import binascii
import os
from uuid import UUID, uuid4

from flask import Flask, jsonify, request
from pydantic import BaseModel, ValidationError
from werkzeug.exceptions import BadRequest, HTTPException
import psycopg

from app.services.incident.errors import ServiceError

from app.api.auth import LocalSessionStore, TokenVerifier, UnavailableTokenVerifier, bearer_token
from app.api.errors import ApiError, unavailable
from app.schemas.contracts import (
    CameraObservationProposal,
    CreateIncidentRequest, CreateShareRequest, EventBatchRequest,
    HelperUpdateRequest, LocationDescriptionRequest, PatchIncidentRequest,
    SceneImageAnalysisRequest, SceneImageAnalysisResponse,
    SceneObservationRequest, ShareSessionRequest, RevokeAccessRequest,
    RuleEvaluationRequest, AedDispatchRequest, AedUnavailabilityRequest,
)
from app.agent.scene_image import SceneImageAnalyzer, default_scene_image_analyzer
from app.services.mock import SyntheticIncidentService
from app.services.ports import IncidentService


def parse_json(model: type[BaseModel]):
    if not request.is_json:
        raise ApiError("invalid_input", 400, "JSON body required")
    try:
        data = request.get_json(silent=False)
    except BadRequest:
        raise ApiError("invalid_input", 400, "Malformed JSON") from None
    return model.model_validate(data)


def parsed_uuid(raw: str) -> UUID:
    try:
        return UUID(raw)
    except ValueError:
        raise ApiError("invalid_input", 400, "Invalid resource ID") from None


def create_app(
    service: IncidentService | None = None,
    verifier: TokenVerifier | None = None,
    scene_image_analyzer: SceneImageAnalyzer | None = None,
) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 1_048_576
    origins = {part.strip() for part in os.getenv("ALLOWED_ORIGINS", "").split(",") if part.strip()}
    if service is None and os.getenv("SYNTHETIC_MOCK_SERVICE") == "1":
        service = SyntheticIncidentService()
    session_store = None
    if service is None and os.getenv("DATABASE_URL"):
        if os.getenv("INCIDENT_BACKEND", "normalized") == "legacy":
            from app.services.postgres import PostgresIncidentService
            service = PostgresIncidentService(os.environ["DATABASE_URL"])
        else:
            from app.api.normalized import NormalizedIncidentService
            key = os.getenv("LOCAL_INVITE_KEY")
            if not key:
                raise RuntimeError("LOCAL_INVITE_KEY is required for normalized invitations")
            service = NormalizedIncidentService(os.environ["DATABASE_URL"], key)
    if os.getenv("DATABASE_URL"):
        session_store = LocalSessionStore(os.environ["DATABASE_URL"])
    verifier = verifier or session_store or UnavailableTokenVerifier()
    scene_image_analyzer = scene_image_analyzer or default_scene_image_analyzer()

    @app.after_request
    def cors(response):
        origin = request.headers.get("Origin")
        if origin in origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, OPTIONS"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.before_request
    def preflight():
        if request.method == "OPTIONS":
            if request.headers.get("Origin") not in origins:
                raise ApiError("unauthorized", 403, "Origin not permitted")
            return "", 204

    @app.errorhandler(ApiError)
    def api_error(exc: ApiError):
        return jsonify({"error": {"code": exc.code, "message": exc.message, "requestId": str(uuid4()), "details": exc.details}}), exc.status

    @app.errorhandler(ServiceError)
    def service_error(exc: ServiceError):
        status = {
            "unauthorized": 403, "expired": 403, "stale_revision": 409,
            "rule_mismatch": 409, "unavailable": 503, "invalid_input": 400,
        }[exc.code]
        return api_error(ApiError(exc.code, status, exc.reason.replace("_", " "), exc.detail))

    @app.errorhandler(psycopg.Error)
    def database_error(exc: psycopg.Error):
        return api_error(unavailable())

    @app.errorhandler(ValidationError)
    def validation_error(exc: ValidationError):
        return jsonify({"error": {"code": "invalid_input", "message": "Invalid request", "requestId": str(uuid4()), "details": {"fields": [{"path": ".".join(map(str, item["loc"])), "reason": item["type"]} for item in exc.errors()]}}}), 400

    @app.errorhandler(HTTPException)
    def http_error(exc: HTTPException):
        if exc.code == 413:
            return api_error(ApiError("invalid_input", 413, "Request too large"))
        return api_error(ApiError("invalid_input", exc.code or 400, "Request could not be processed"))

    def uid() -> str:
        return verifier.verify(bearer_token(request.headers.get("Authorization")))

    def svc() -> IncidentService:
        if service is None:
            raise unavailable()
        return service

    def ok(model, status=200):
        return jsonify(model.model_dump(mode="json")), status

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    @app.post("/v1/sessions")
    def sessions():
        if session_store is None:
            raise unavailable()
        return ok(session_store.create(), 201)

    @app.post("/v1/incidents")
    def incidents():
        actor = uid()
        return ok(svc().create_incident(actor, parse_json(CreateIncidentRequest)), 201)

    @app.post("/v1/incidents/<incident_id>/event-batches")
    def event_batches(incident_id):
        actor = uid()
        return ok(svc().upload_events(actor, parsed_uuid(incident_id), parse_json(EventBatchRequest)))

    @app.post("/v1/incidents/<incident_id>/scene-observations")
    def scene_observations(incident_id):
        actor = uid()
        return ok(svc().add_observations(actor, parsed_uuid(incident_id), parse_json(SceneObservationRequest)))

    @app.post("/v1/incidents/<incident_id>/scene-image-analyses")
    def scene_image_analyses(incident_id):
        actor = uid()
        resource_id = parsed_uuid(incident_id)
        body = parse_json(SceneImageAnalysisRequest)
        view = svc().authorize(actor, resource_id, {"primary"})
        if view.status.value != "active" or view.interactionMode.value == "handover":
            raise ApiError("expired", 403, "Incident no longer accepts scene images")
        if body.expectedModeRevision != view.modeRevision:
            raise ApiError(
                "stale_revision", 409, "Mode revision changed",
                {"field": "modeRevision", "current": view.modeRevision},
            )
        try:
            image = base64.b64decode(body.imageBase64, validate=True)
        except (binascii.Error, ValueError):
            raise ApiError("invalid_input", 400, "Invalid image encoding") from None
        if not image or len(image) > 700_000:
            raise ApiError("invalid_input", 400, "Image must be 700 KB or smaller")
        if body.mimeType == "image/jpeg" and not image.startswith(b"\xff\xd8\xff"):
            raise ApiError("invalid_input", 400, "Image content does not match MIME type")
        if body.mimeType == "image/webp" and not (
            image.startswith(b"RIFF") and image[8:12] == b"WEBP"
        ):
            raise ApiError("invalid_input", 400, "Image content does not match MIME type")

        result = scene_image_analyzer.analyze(image, body.mimeType, body.capturedAt)
        latest_view = svc().authorize(actor, resource_id, {"primary"})
        if (
            latest_view.status.value != "active"
            or latest_view.interactionMode.value == "handover"
            or latest_view.modeRevision != body.expectedModeRevision
        ):
            raise ApiError(
                "stale_revision", 409, "Mode revision changed during image analysis",
                {"field": "modeRevision", "current": latest_view.modeRevision},
            )
        risk_fields = (
            ("hazards.traffic", "traffic", result.traffic),
            ("hazards.fire", "fire", result.fire),
            ("hazards.standingWater", "standing_water", result.standing_water),
            ("hazards.crowd", "crowd", result.crowd),
        )
        proposals = [
            CameraObservationProposal(
                observationId=uuid4(), key=key,
                value=True if value == "present" else False if value == "absent" else "unknown",
                observedAt=result.captured_at,
                confidence=result.confidence.get(confidence_key, "unknown"),
            )
            for key, confidence_key, value in risk_fields
        ]
        proposals.append(CameraObservationProposal(
            observationId=uuid4(), key="patient.bleeding",
            value=result.bleeding_severity, observedAt=result.captured_at,
            confidence=result.confidence.get("bleeding_severity", "unknown"),
        ))
        return ok(SceneImageAnalysisResponse(
            analysisId=uuid4(), model=result.model, proposals=proposals,
            warnings=result.warnings,
        ))

    @app.post("/v1/incidents/<incident_id>/location-descriptions")
    def location_descriptions(incident_id):
        actor = uid()
        return ok(svc().describe_location(actor, parsed_uuid(incident_id), parse_json(LocationDescriptionRequest)))

    @app.post("/v1/incidents/<incident_id>/shares")
    def shares(incident_id):
        actor = uid()
        return ok(svc().create_share(actor, parsed_uuid(incident_id), parse_json(CreateShareRequest)), 201)

    @app.post("/v1/incidents/<incident_id>/access-revocations")
    def revoke_access(incident_id):
        actor = uid()
        return ok(svc().revoke_access(actor, parsed_uuid(incident_id), parse_json(RevokeAccessRequest)), 201)

    @app.post("/v1/share-sessions")
    def share_sessions():
        actor = uid()
        return ok(svc().exchange_share(actor, parse_json(ShareSessionRequest)), 201)

    @app.post("/v1/incidents/<incident_id>/helpers/<helper_id>/updates")
    def helper_updates(incident_id, helper_id):
        actor = uid()
        return ok(svc().update_helper(actor, parsed_uuid(incident_id), parsed_uuid(helper_id), parse_json(HelperUpdateRequest)))

    @app.get("/v1/incidents/<incident_id>/aeds")
    def aeds(incident_id):
        actor = uid()
        try:
            limit = int(request.args.get("limit", "10"))
        except ValueError:
            raise ApiError("invalid_input", 400, "Invalid limit") from None
        if not 1 <= limit <= 20:
            raise ApiError("invalid_input", 400, "Invalid limit")
        latitude = request.args.get("lat")
        longitude = request.args.get("lng")
        if (latitude is None) != (longitude is None):
            raise ApiError("invalid_input", 400, "lat and lng are required together")
        if latitude is not None:
            try:
                lat, lng = float(latitude), float(longitude)
            except ValueError:
                raise ApiError("invalid_input", 400, "Invalid coordinates") from None
            if not -90 <= lat <= 90 or not -180 <= lng <= 180:
                raise ApiError("invalid_input", 400, "Invalid coordinates")
            return ok(svc().list_aeds(actor, parsed_uuid(incident_id), limit, lat=lat, lng=lng))
        return ok(svc().list_aeds(actor, parsed_uuid(incident_id), limit))

    @app.get("/v1/incidents/<incident_id>/snapshot")
    def snapshot(incident_id):
        actor = uid()
        return ok(svc().get_snapshot(actor, parsed_uuid(incident_id)))

    @app.get("/v1/incidents/<incident_id>/handoff/events")
    def handoff_events(incident_id):
        actor = uid()
        try:
            limit = int(request.args.get("limit", "25"))
        except ValueError:
            raise ApiError("invalid_input", 400, "Invalid limit") from None
        if not 1 <= limit <= 100:
            raise ApiError("invalid_input", 400, "Invalid limit")
        return ok(svc().handoff_events(actor, parsed_uuid(incident_id), request.args.get("cursor"), limit))

    @app.post("/v1/incidents/<incident_id>/rule-evaluations")
    def rule_evaluations(incident_id):
        actor = uid()
        selected = svc()
        if not hasattr(selected, "evaluate_rules"):
            raise unavailable()
        return ok(selected.evaluate_rules(actor, parsed_uuid(incident_id), parse_json(RuleEvaluationRequest)))

    @app.get("/v1/incidents/<incident_id>/handoff")
    def handoff(incident_id):
        actor = uid()
        selected = svc()
        if not hasattr(selected, "handoff"):
            raise unavailable()
        try:
            limit = int(request.args.get("limit", "25"))
        except ValueError:
            raise ApiError("invalid_input", 400, "Invalid limit") from None
        if not 1 <= limit <= 100:
            raise ApiError("invalid_input", 400, "Invalid limit")
        return ok(selected.handoff(actor, parsed_uuid(incident_id), request.args.get("cursor"), limit))

    @app.post("/v1/incidents/<incident_id>/aed-assignments")
    def dispatch_aed(incident_id):
        actor = uid()
        selected = svc()
        if not hasattr(selected, "dispatch_aed"):
            raise unavailable()
        return ok(selected.dispatch_aed(actor, parsed_uuid(incident_id), parse_json(AedDispatchRequest)), 201)

    @app.get("/v1/incidents/<incident_id>/helpers/<helper_id>/aed-assignment")
    def aed_assignment(incident_id, helper_id):
        actor = uid()
        selected = svc()
        if not hasattr(selected, "get_aed_assignment"):
            raise unavailable()
        return ok(selected.get_aed_assignment(
            actor, parsed_uuid(incident_id), parsed_uuid(helper_id),
        ))

    @app.post("/v1/incidents/<incident_id>/helpers/<helper_id>/aed-unavailability-reports")
    def aed_unavailable(incident_id, helper_id):
        actor = uid()
        selected = svc()
        if not hasattr(selected, "report_aed_unavailable"):
            raise unavailable()
        return ok(selected.report_aed_unavailable(
            actor, parsed_uuid(incident_id), parsed_uuid(helper_id),
            parse_json(AedUnavailabilityRequest),
        ))

    @app.patch("/v1/incidents/<incident_id>")
    def patch_incident(incident_id):
        actor = uid()
        return ok(svc().patch_incident(actor, parsed_uuid(incident_id), parse_json(PatchIncidentRequest)))

    from app.api.live import register_live
    register_live(app, service, verifier, origins)
    return app
