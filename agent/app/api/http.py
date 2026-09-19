from __future__ import annotations

import os
from uuid import UUID, uuid4

from flask import Flask, jsonify, request
from pydantic import BaseModel, ValidationError
from werkzeug.exceptions import BadRequest, HTTPException

from app.api.auth import FirebaseTokenVerifier, TokenVerifier, bearer_token
from app.api.errors import ApiError, unavailable
from app.schemas.contracts import (
    CreateIncidentRequest, CreateShareRequest, EventBatchRequest,
    HelperUpdateRequest, LocationDescriptionRequest, PatchIncidentRequest,
    SceneObservationRequest, ShareSessionRequest,
)
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


def create_app(service: IncidentService | None = None, verifier: TokenVerifier | None = None) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 1_048_576
    origins = {part.strip() for part in os.getenv("ALLOWED_ORIGINS", "").split(",") if part.strip()}
    if service is None and os.getenv("SYNTHETIC_MOCK_SERVICE") == "1":
        service = SyntheticIncidentService()
    verifier = verifier or FirebaseTokenVerifier()

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

    @app.post("/v1/incidents/<incident_id>/location-descriptions")
    def location_descriptions(incident_id):
        actor = uid()
        return ok(svc().describe_location(actor, parsed_uuid(incident_id), parse_json(LocationDescriptionRequest)))

    @app.post("/v1/incidents/<incident_id>/shares")
    def shares(incident_id):
        actor = uid()
        return ok(svc().create_share(actor, parsed_uuid(incident_id), parse_json(CreateShareRequest)), 201)

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
        return ok(svc().list_aeds(actor, parsed_uuid(incident_id), limit))

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

    @app.patch("/v1/incidents/<incident_id>")
    def patch_incident(incident_id):
        actor = uid()
        return ok(svc().patch_incident(actor, parsed_uuid(incident_id), parse_json(PatchIncidentRequest)))

    from app.api.live import register_live
    register_live(app, service, verifier, origins)
    return app
