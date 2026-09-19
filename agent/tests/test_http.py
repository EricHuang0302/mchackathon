from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.api.http import create_app
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
