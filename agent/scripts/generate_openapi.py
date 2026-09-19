"""Generate the checked HTTP contract from Pydantic transport models."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic.json_schema import models_json_schema

from app.schemas import contracts as c


MODELS = [
    c.ErrorBody, c.ErrorResponse, c.SessionResponse, c.CreateIncidentRequest, c.IncidentView,
    c.EventInput, c.EventBatchRequest, c.EventAck, c.EventBatchResponse,
    c.LocationPointInput, c.ObservationInput, c.ObservationRecord,
    c.SceneObservationRequest, c.SceneObservationResponse,
    c.SceneImageAnalysisRequest, c.CameraObservationProposal, c.SceneImageAnalysisResponse,
    c.LocationDescriptionRequest, c.LocationCandidate, c.LocationDescriptionResponse,
    c.CreateShareRequest, c.CreateShareResponse, c.RevokeAccessRequest, c.RevokeAccessResponse, c.ShareSessionRequest,
    c.ShareSessionResponse, c.HelperUpdateRequest, c.HelperUpdateResponse,
    c.AedCandidate, c.AedListResponse, c.SceneSnapshotResponse, c.HandoffEvent, c.HandoffEventsResponse,
    c.RuleEvaluationRequest, c.RuleEvaluationResponse, c.HandoffReadResponse,
    c.AedDispatchRequest, c.AedUnavailabilityRequest, c.AedAssignmentResponse,
    c.AedAssignmentReadResponse,
    c.PatchIncidentRequest,
]


def ref(model):
    return {"$ref": f"#/components/schemas/{model.__name__}"}


def response(model, status="200"):
    return {status: {"description": "Success", "content": {"application/json": {"schema": ref(model)}}}}


def operation(summary, model, result, status="200", *, query=None, authenticated=True):
    value = {
        "summary": summary, "security": [{"LocalSessionToken": []}] if authenticated else [],
        "responses": {**response(result, status),
            "400": {"$ref": "#/components/responses/BadRequest"},
            "401": {"$ref": "#/components/responses/Unauthorized"},
            "403": {"$ref": "#/components/responses/Forbidden"},
            "409": {"$ref": "#/components/responses/Conflict"},
            "503": {"$ref": "#/components/responses/Unavailable"}},
    }
    if model:
        value["requestBody"] = {"required": True, "content": {"application/json": {"schema": ref(model)}}}
    if query:
        value["parameters"] = [{"name": name, "in": "query", "required": False, "schema": schema} for name, schema in query.items()]
    return value


def build():
    _, schemas = models_json_schema([(model, "validation") for model in MODELS], ref_template="#/components/schemas/{model}")
    definitions = schemas["$defs"]
    error_responses = {}
    for name, status in [("BadRequest", "400"), ("Unauthorized", "401"), ("Forbidden", "403"), ("Conflict", "409"), ("Unavailable", "503")]:
        error_responses[name] = {"description": name, "content": {"application/json": {"schema": ref(c.ErrorResponse)}}}
    incident = {"name": "incidentId", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}}
    helper = {"name": "helperId", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}}
    paths = {
        "/v1/sessions": {"post": operation("Create an expiring local session", None, c.SessionResponse, "201", authenticated=False)},
        "/v1/incidents": {"post": operation("Register an incident idempotently", c.CreateIncidentRequest, c.IncidentView, "201")},
        "/v1/incidents/{incidentId}/event-batches": {"parameters": [incident], "post": operation("Upload ordered events", c.EventBatchRequest, c.EventBatchResponse)},
        "/v1/incidents/{incidentId}/scene-observations": {"parameters": [incident], "post": operation("Project typed scene observations", c.SceneObservationRequest, c.SceneObservationResponse)},
        "/v1/incidents/{incidentId}/scene-image-analyses": {"parameters": [incident], "post": operation("Analyze one optional scene image into unconfirmed proposals", c.SceneImageAnalysisRequest, c.SceneImageAnalysisResponse)},
        "/v1/incidents/{incidentId}/location-descriptions": {"parameters": [incident], "post": operation("Describe authorized coordinates", c.LocationDescriptionRequest, c.LocationDescriptionResponse)},
        "/v1/incidents/{incidentId}/shares": {"parameters": [incident], "post": operation("Create expiring participant invitation", c.CreateShareRequest, c.CreateShareResponse, "201")},
        "/v1/incidents/{incidentId}/access-revocations": {"parameters": [incident], "post": operation("Revoke all pending invitations and active grants", c.RevokeAccessRequest, c.RevokeAccessResponse, "201")},
        "/v1/share-sessions": {"post": operation("Redeem participant invitation", c.ShareSessionRequest, c.ShareSessionResponse, "201")},
        "/v1/incidents/{incidentId}/helpers/{helperId}/updates": {"parameters": [incident, helper], "post": operation("Report own helper status or location", c.HelperUpdateRequest, c.HelperUpdateResponse)},
        "/v1/incidents/{incidentId}/aeds": {"parameters": [incident], "get": operation("List scoped AED candidates", None, c.AedListResponse, query={"limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10}, "lat": {"type": "number", "minimum": -90, "maximum": 90}, "lng": {"type": "number", "minimum": -180, "maximum": 180}})},
        "/v1/incidents/{incidentId}/aed-assignments": {"parameters": [incident], "post": operation("Dispatch a helper to an AED candidate", c.AedDispatchRequest, c.AedAssignmentResponse, "201")},
        "/v1/incidents/{incidentId}/helpers/{helperId}/aed-assignment": {"parameters": [incident, helper], "get": operation("Read the helper's current AED assignment", None, c.AedAssignmentReadResponse)},
        "/v1/incidents/{incidentId}/helpers/{helperId}/aed-unavailability-reports": {"parameters": [incident, helper], "post": operation("Report an unavailable AED and attempt reassignment", c.AedUnavailabilityRequest, c.AedAssignmentResponse)},
        "/v1/incidents/{incidentId}/rule-evaluations": {"parameters": [incident], "post": operation("Evaluate the pinned reviewed-rule package without committing a decision", c.RuleEvaluationRequest, c.RuleEvaluationResponse)},
        "/v1/incidents/{incidentId}/handoff": {"parameters": [incident], "get": operation("Read a snapshot-first MIST and sanitized timeline at one boundary", None, c.HandoffReadResponse, query={"cursor": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25}})},
        "/v1/incidents/{incidentId}/snapshot": {"parameters": [incident], "get": operation("Read scoped canonical scene snapshot", None, c.SceneSnapshotResponse)},
        "/v1/incidents/{incidentId}/handoff/events": {"parameters": [incident], "get": operation("Read paginated sanitized timeline", None, c.HandoffEventsResponse, query={"cursor": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25}})},
        "/v1/incidents/{incidentId}": {"parameters": [incident], "patch": operation("Update incident status with revision", c.PatchIncidentRequest, c.IncidentView)},
    }
    return {
        "openapi": "3.1.0", "info": {"title": "First Aid Copilot Agent API", "version": "0.2.0", "description": "Normalized local PostgreSQL integration. Unreviewed demo rules and optional external data are clearly labeled."},
        "paths": paths,
        "components": {"schemas": definitions, "responses": error_responses, "securitySchemes": {"LocalSessionToken": {"type": "http", "scheme": "bearer", "bearerFormat": "opaque local session token"}}},
        "x-websocket": {"path": "/v1/incidents/{incidentId}/live", "firstMessage": "auth with token and LiveEnvelope session.hello", "clientPayloads": ["mode.silence", "resume.request", "media.frame"], "serverPayloads": ["session.ready", "mode.silenced", "resume.accepted", "media.ack", "observation.proposed", "error"], "reconnectVoiceAllowed": False},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = Path(__file__).resolve().parents[1] / "openapi.json"
    rendered = json.dumps(build(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if path.read_text() != rendered:
            raise SystemExit("openapi.json differs from Pydantic contracts")
    else:
        path.write_text(rendered)


if __name__ == "__main__":
    main()
