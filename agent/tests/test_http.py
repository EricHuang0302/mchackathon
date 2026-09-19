from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.api.http import create_app
from app.agent.scene_image import SceneImageResult
import app.services.mock as mock_service
from app.services.mock import SyntheticIncidentService


class Verifier:
    def verify(self, token):
        if token in {"alice", "bob", "ems", "runner"}:
            return token
        raise ValueError("invalid test token")


@pytest.fixture
def client():
    return create_app(service=SyntheticIncidentService(), verifier=Verifier()).test_client()


def auth(uid="alice"):
    return {"Authorization": f"Bearer {uid}"}


def incident(client):
    incident_id, client_id = uuid4(), uuid4()
    response = client.post("/v1/incidents", headers=auth(), json={"incidentId": str(incident_id), "primaryClientId": str(client_id), "ruleVersion": "demo-v1"})
    assert response.status_code == 201
    return incident_id, client_id


class FakeSceneImageAnalyzer:
    def __init__(self):
        self.calls = []

    def analyze(self, image, mime_type, captured_at):
        self.calls.append((image, mime_type, captured_at))
        return SceneImageResult(
            model="synthetic-vision", captured_at=captured_at,
            traffic="present", fire="absent", standing_water="unknown",
            crowd="absent", bleeding_severity="severe",
            confidence={"traffic": "high", "bleeding_severity": "medium"},
            warnings=["The full scene is not visible."],
        )


def event(client_id, sequence, state_revision, mode_revision, *, event_id=None, kind="action.reported", detail=None):
    return {
        "eventId": str(event_id or uuid4()), "type": kind,
        "detail": detail or {"action": "cpr_started"}, "clientId": str(client_id),
        "clientInstanceId": "2bc8a203-21cc-4d95-9a0a-ef22ee924679",
        "clientSequence": sequence, "clientTime": datetime.now(timezone.utc).isoformat(),
        "authorityEpoch": 1, "stateRevision": state_revision,
        "modeRevision": mode_revision, "ruleVersion": "demo-v1",
    }


def test_incident_auth_scope_and_unavailable(client):
    incident_id, _ = incident(client)
    path = f"/v1/incidents/{incident_id}/aeds"
    assert client.get(path).status_code == 401
    assert client.get(path, headers=auth("bob")).status_code == 403
    assert client.get(path, headers=auth()).json["candidates"] == []
    assert client.post(f"/v1/incidents/{incident_id}/location-descriptions", headers=auth(), json={"lat": 25.0, "lng": 121.0}).status_code == 503


def test_events_duplicates_stale_revision_and_mode(client):
    incident_id, client_id = incident(client)
    path = f"/v1/incidents/{incident_id}/event-batches"
    first = event(client_id, 1, 0, 0)
    response = client.post(path, headers=auth(), json={"events": [first]})
    assert response.json["acknowledgements"][0]["status"] == "accepted"
    assert response.json["stateRevision"] == 1
    duplicate = client.post(path, headers=auth(), json={"events": [first]})
    assert duplicate.json["acknowledgements"][0]["status"] == "duplicate"
    assert duplicate.json["stateRevision"] == 1
    altered = dict(first, detail={"action": "aed_obtained"})
    conflict = client.post(path, headers=auth(), json={"events": [altered]})
    assert conflict.json["acknowledgements"][0]["status"] == "conflict"
    obsolete = event(client_id, 2, 0, 0)
    stale_response = client.post(path, headers=auth(), json={"events": [obsolete]})
    assert stale_response.json["acknowledgements"][0]["code"] == "stale_revision"
    dial = event(client_id, 2, 1, 1, kind="mode.changed", detail={"interactionMode": "on_call", "reason": "dial_started"})
    muted = client.post(path, headers=auth(), json={"events": [dial]})
    assert muted.json["modeRevision"] == 1
    assert muted.json["stateRevision"] == 2


def test_scene_snapshot_revision_and_share_permissions(client):
    incident_id, _ = incident(client)
    path = f"/v1/incidents/{incident_id}"
    observation_id, key = uuid4(), uuid4()
    body = {"observations": [{"observationId": str(observation_id), "key": "breathing_reported", "value": "unknown", "source": "camera_proposal", "observedAt": datetime.now(timezone.utc).isoformat(), "confirmation": "proposed", "evidenceEventIds": []}], "expectedSnapshotRevision": 0, "idempotencyKey": str(key)}
    accepted = client.post(path + "/scene-observations", headers=auth(), json=body)
    assert accepted.json["snapshotRevision"] == 1
    snapshot = client.get(path + "/snapshot", headers=auth()).json
    assert snapshot["observations"][0]["key"] == "patient.breathing"
    assert client.post(path + "/scene-observations", headers=auth(), json=body).json == accepted.json
    body["idempotencyKey"] = str(uuid4())
    assert client.post(path + "/scene-observations", headers=auth(), json=body).status_code == 409
    runner_id = uuid4()
    share = client.post(path + "/shares", headers=auth(), json={"scope": "aed_runner", "helperId": str(runner_id), "expiresInSeconds": 60, "idempotencyKey": str(uuid4())})
    assert share.status_code == 201
    exchanged = client.post("/v1/share-sessions", headers=auth("runner"), json={"secret": share.json["secret"]})
    assert exchanged.json["scope"] == "aed_runner"
    assert client.get(path + "/handoff/events", headers=auth("runner")).status_code == 403
    assert client.get(path + "/aeds", headers=auth("runner")).status_code == 200
    assert client.post(path + "/helpers/" + str(uuid4()) + "/updates", headers=auth("runner"), json={"updateId": str(uuid4()), "expectedAssignmentRevision": 0, "status": "en_route", "reportedAt": datetime.now(timezone.utc).isoformat()}).status_code == 403


def test_scene_image_analysis_is_scoped_revisioned_and_unconfirmed():
    analyzer = FakeSceneImageAnalyzer()
    local_client = create_app(
        service=SyntheticIncidentService(), verifier=Verifier(),
        scene_image_analyzer=analyzer,
    ).test_client()
    incident_id, _ = incident(local_client)
    path = f"/v1/incidents/{incident_id}/scene-image-analyses"
    captured_at = datetime.now(timezone.utc).isoformat()
    image = base64.b64encode(b"\xff\xd8\xffsynthetic-jpeg").decode()
    body = {
        "imageBase64": image, "mimeType": "image/jpeg",
        "capturedAt": captured_at, "expectedModeRevision": 0,
    }

    assert local_client.post(path, headers=auth("bob"), json=body).status_code == 403
    stale_body = dict(body, expectedModeRevision=1)
    assert local_client.post(path, headers=auth(), json=stale_body).status_code == 409
    assert analyzer.calls == []

    response = local_client.post(path, headers=auth(), json=body)
    assert response.status_code == 200
    assert len(analyzer.calls) == 1
    assert response.json["model"] == "synthetic-vision"
    assert response.json["warnings"] == ["The full scene is not visible."]
    proposals = {item["key"]: item for item in response.json["proposals"]}
    assert proposals["hazards.traffic"]["value"] is True
    assert proposals["hazards.standingWater"]["value"] == "unknown"
    assert proposals["patient.bleeding"]["value"] == "severe"
    assert all(item["confirmation"] == "proposed" for item in proposals.values())
    assert all(item["source"] == "camera_proposal" for item in proposals.values())


def test_scene_image_rejects_mime_spoof_before_analysis():
    analyzer = FakeSceneImageAnalyzer()
    local_client = create_app(
        service=SyntheticIncidentService(), verifier=Verifier(),
        scene_image_analyzer=analyzer,
    ).test_client()
    incident_id, _ = incident(local_client)
    response = local_client.post(
        f"/v1/incidents/{incident_id}/scene-image-analyses",
        headers=auth(),
        json={
            "imageBase64": base64.b64encode(b"not-a-jpeg").decode(),
            "mimeType": "image/jpeg", "capturedAt": datetime.now(timezone.utc).isoformat(),
            "expectedModeRevision": 0,
        },
    )
    assert response.status_code == 400
    assert analyzer.calls == []


def test_share_exchange_reports_stable_failure_reasons(monkeypatch):
    current = datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(mock_service, "now", lambda: current)
    local_client = create_app(service=SyntheticIncidentService(), verifier=Verifier()).test_client()

    def create_share():
        incident_id, _ = incident(local_client)
        response = local_client.post(
            f"/v1/incidents/{incident_id}/shares",
            headers=auth(),
            json={"scope": "ems_viewer", "expiresInSeconds": 60, "idempotencyKey": str(uuid4())},
        )
        assert response.status_code == 201
        return incident_id, response.json["secret"]

    _, expired_secret = create_share()
    current += timedelta(seconds=61)
    expired = local_client.post("/v1/share-sessions", headers=auth("bob"), json={"secret": expired_secret})
    assert expired.json["error"]["details"]["reason"] == "invitation_expired"
    unknown = local_client.post("/v1/share-sessions", headers=auth("bob"), json={"secret": "x" * 32})
    assert unknown.json["error"]["details"]["reason"] == "invitation_expired"

    _, redeemed_secret = create_share()
    assert local_client.post("/v1/share-sessions", headers=auth("bob"), json={"secret": redeemed_secret}).status_code == 201
    redeemed = local_client.post("/v1/share-sessions", headers=auth("ems"), json={"secret": redeemed_secret})
    assert redeemed.json["error"]["details"]["reason"] == "invitation_redeemed"

    revoked_incident, revoked_secret = create_share()
    revoked = local_client.post(
        f"/v1/incidents/{revoked_incident}/access-revocations",
        headers=auth(),
        json={"expectedStateRevision": 0, "idempotencyKey": str(uuid4())},
    )
    assert revoked.status_code == 201
    revoked_exchange = local_client.post("/v1/share-sessions", headers=auth("bob"), json={"secret": revoked_secret})
    assert revoked_exchange.json["error"]["details"]["reason"] == "invitation_revoked"

    _, owner_secret = create_share()
    denied = local_client.post("/v1/share-sessions", headers=auth(), json={"secret": owner_secret})
    assert denied.json["error"]["details"]["reason"] == "permission_denied"
    assert local_client.post("/v1/share-sessions", headers=auth("bob"), json={"secret": owner_secret}).status_code == 201


def test_patch_requires_current_revision(client):
    incident_id, _ = incident(client)
    path = f"/v1/incidents/{incident_id}"
    assert client.patch(path, headers=auth(), json={"status": "closed", "expectedStateRevision": 1}).status_code == 409
    closed = client.patch(path, headers=auth(), json={"status": "closed", "expectedStateRevision": 0})
    assert closed.json["status"] == "closed"
    assert closed.json["interactionMode"] == "handover"
    assert client.get(path + "/aeds", headers=auth()).status_code == 403


def test_missing_service_fails_closed():
    client = create_app(verifier=Verifier()).test_client()
    response = client.post("/v1/incidents", headers=auth(), json={"incidentId": str(uuid4()), "primaryClientId": str(uuid4()), "ruleVersion": "demo-v1"})
    assert response.status_code == 503
