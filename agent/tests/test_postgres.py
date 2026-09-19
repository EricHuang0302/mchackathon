"""Real PostgreSQL integration checks (set PG_TEST_DSN)."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

import psycopg
import pytest

from app.api.auth import LocalSessionStore
from app.api.errors import ApiError
from app.api.http import create_app
from app.api.live import LiveSession
from app.services.postgres import PostgresIncidentService


@pytest.fixture
def database(monkeypatch):
    dsn = os.getenv("PG_TEST_DSN")
    if not dsn:
        pytest.skip("Set PG_TEST_DSN for PostgreSQL integration checks")
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("INCIDENT_BACKEND", "legacy")
    monkeypatch.setenv("LOCAL_INVITE_KEY", "2Sjh2HSd8E-Vs7H4qv2mRtUsGS68VKZTJh4pHcB5WjM=")
    with psycopg.connect(dsn) as connection:
        connection.execute("DROP TABLE IF EXISTS app_state")
        connection.execute("DROP TABLE IF EXISTS local_sessions")
    return create_app().test_client(), dsn


def session(client):
    response = client.post("/v1/sessions")
    assert response.status_code == 201
    token = response.json["sessionToken"]
    return token, {"Authorization": f"Bearer {token}"}


def event(client_id, sequence, state, mode, kind="action.reported", detail=None):
    return {
        "eventId": str(uuid4()), "type": kind, "detail": detail or {"action": "synthetic_action"},
        "clientId": str(client_id), "clientInstanceId": "2bc8a203-21cc-4d95-9a0a-ef22ee924679",
        "clientSequence": sequence, "clientTime": datetime.now(timezone.utc).isoformat(),
        "authorityEpoch": 1, "stateRevision": state, "modeRevision": mode, "ruleVersion": "demo-v1",
    }


def envelope(incident_id, client_id, state, mode, sequence, kind):
    return {
        "protocolVersion": 1, "messageId": str(uuid4()), "incidentId": str(incident_id),
        "clientId": str(client_id), "clientInstanceId": "33333333-3333-4333-8333-333333333333",
        "clientSequence": sequence, "clientTime": datetime.now(timezone.utc).isoformat(),
        "authorityEpoch": 1, "stateRevision": state, "modeRevision": mode, "payload": {"type": kind},
    }


def test_postgres_auth_persistence_revisions_and_scope(database):
    client, dsn = database
    owner_token, owner = session(client)
    runner_token, runner = session(client)
    _, stranger = session(client)
    incident_id, client_id = uuid4(), uuid4()
    path = f"/v1/incidents/{incident_id}"
    body = {"incidentId": str(incident_id), "primaryClientId": str(client_id), "ruleVersion": "demo-v1"}
    assert client.post("/v1/incidents", headers=owner, json=body).status_code == 201
    assert client.post("/v1/incidents", headers=owner, json=body).status_code == 201
    assert client.get(path + "/snapshot").status_code == 401
    assert client.get(path + "/snapshot", headers=stranger).status_code == 403
    first = event(client_id, 1, 0, 0)
    events_path = path + "/event-batches"
    assert client.post(events_path, headers=owner, json={"events": [first]}).json["acknowledgements"][0]["status"] == "accepted"
    assert client.post(events_path, headers=owner, json={"events": [first]}).json["acknowledgements"][0]["status"] == "duplicate"
    assert client.post(events_path, headers=owner, json={"events": [event(client_id, 2, 0, 0)]}).json["acknowledgements"][0]["code"] == "stale_revision"
    rebooted = create_app().test_client()
    dial = event(client_id, 2, 1, 1, "mode.changed", {"interactionMode": "on_call", "reason": "dial_started"})
    assert rebooted.post(events_path, headers=owner, json={"events": [dial]}).json["modeRevision"] == 1
    live = LiveSession(PostgresIncidentService(dsn), LocalSessionStore(dsn))
    ready = live.authenticate({"type": "auth", "token": owner_token, "envelope": envelope(incident_id, client_id, 2, 1, 1, "session.hello")}, incident_id)
    assert ready["voiceAllowed"] is False and ready["resumeRequired"] is True
    with pytest.raises(ApiError) as error:
        live.receive(envelope(incident_id, client_id, 2, 1, 2, "resume.request"))
    assert getattr(error.value, "status", None) == 403
    live.close()
    observation = {"observations": [{"observationId": str(uuid4()), "key": "breathing_reported", "value": "unknown", "source": "manual_report", "observedAt": datetime.now(timezone.utc).isoformat(), "confirmation": "uncertain", "evidenceEventIds": []}], "expectedSnapshotRevision": 0, "idempotencyKey": str(uuid4())}
    projected = rebooted.post(path + "/scene-observations", headers=owner, json=observation)
    assert projected.json["snapshotRevision"] == 1
    assert client.get(path + "/snapshot", headers=owner).json["observations"][0]["value"] == "unknown"
    assert rebooted.post(path + "/scene-observations", headers=owner, json=observation).json == projected.json
    stale_observation = dict(observation, idempotencyKey=str(uuid4()))
    assert rebooted.post(path + "/scene-observations", headers=owner, json=stale_observation).status_code == 409
    assert rebooted.post(path + "/location-descriptions", headers=owner, json={"lat": 25.0, "lng": 121.0}).status_code == 503

    helper_id = uuid4()
    share = rebooted.post(path + "/shares", headers=owner, json={"scope": "aed_runner", "helperId": str(helper_id), "expiresInSeconds": 60, "idempotencyKey": str(uuid4())})
    assert share.status_code == 201
    with psycopg.connect(dsn) as connection:
        assert share.json["secret"] not in str(connection.execute("SELECT data FROM app_state").fetchone()[0])
    assert client.post("/v1/share-sessions", headers=runner, json={"secret": share.json["secret"]}).status_code == 201
    assert client.post("/v1/share-sessions", headers=runner, json={"secret": share.json["secret"]}).status_code == 403
    assert rebooted.get(path + "/aeds", headers=runner).status_code == 200
    helper_path = path + f"/helpers/{helper_id}/updates"
    update = {"updateId": str(uuid4()), "expectedAssignmentRevision": 0, "status": "en_route", "reportedAt": datetime.now(timezone.utc).isoformat()}
    first_update = client.post(helper_path, headers=runner, json=update)
    assert first_update.json["assignmentRevision"] == 1
    assert client.post(helper_path, headers=runner, json=update).json == first_update.json
    assert client.post(helper_path, headers=runner, json=dict(update, updateId=str(uuid4()))).status_code == 409
    second_update = dict(update, updateId=str(uuid4()), expectedAssignmentRevision=1, status="arrived")
    assert client.post(helper_path, headers=runner, json=second_update).json["assignmentRevision"] == 2
    assert client.post(helper_path, headers=runner, json=update).json == first_update.json
    assert rebooted.get(path + "/snapshot", headers=runner).status_code == 403
    assert rebooted.get(path + "/handoff/events", headers=runner).status_code == 403
    assert rebooted.get(path + "/aeds", headers=stranger).status_code == 403
    # Owner can revoke both a redeemed grant and a pending invitation atomically.
    pending = client.post(path + "/shares", headers=owner, json={"scope": "ambulance_greeter", "helperId": str(uuid4()), "expiresInSeconds": 60, "idempotencyKey": str(uuid4())})
    key = str(uuid4())
    revoke_body = {"expectedStateRevision": 2, "idempotencyKey": key}
    revoked = rebooted.post(path + "/access-revocations", headers=owner, json=revoke_body)
    assert revoked.status_code == 201
    assert revoked.json["revokedGrants"] == 1 and revoked.json["revokedInvitations"] == 1
    assert rebooted.post(path + "/access-revocations", headers=owner, json=revoke_body).json == revoked.json
    assert rebooted.get(path + "/aeds", headers=runner).status_code == 403
    assert rebooted.post("/v1/share-sessions", headers=stranger, json={"secret": pending.json["secret"]}).status_code == 403
    assert rebooted.post(path + "/access-revocations", headers=runner, json={"expectedStateRevision": 3, "idempotencyKey": str(uuid4())}).status_code == 403
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE local_sessions SET expires_at = now() - interval '1 second' WHERE token_hash = %s", (sha256(runner_token.encode()).hexdigest(),))
    assert rebooted.get(path + "/aeds", headers=runner).status_code == 401


def test_database_outage_returns_unavailable(database):
    client, dsn = database
    token, owner = session(client)
    verifier = LocalSessionStore(dsn)
    verifier.dsn = "postgresql://app@127.0.0.1:1/absent?connect_timeout=1"
    from app.api.errors import ApiError
    with pytest.raises(ApiError) as error:
        verifier.verify(token)
    assert error.value.status == 503
    service = PostgresIncidentService(dsn)
    service.dsn = verifier.dsn
    broken = create_app(service=service, verifier=LocalSessionStore(dsn)).test_client()
    response = broken.post("/v1/incidents", headers=owner, json={"incidentId": str(uuid4()), "primaryClientId": str(uuid4()), "ruleVersion": "demo-v1"})
    assert response.status_code == 503
    assert response.json["error"]["code"] == "unavailable"


def test_expired_grant_and_incident_retention(database):
    client, dsn = database
    _, owner = session(client)
    _, runner = session(client)
    incident_id, client_id, helper_id = uuid4(), uuid4(), uuid4()
    path = f"/v1/incidents/{incident_id}"
    assert client.post("/v1/incidents", headers=owner, json={"incidentId": str(incident_id), "primaryClientId": str(client_id), "ruleVersion": "demo-v1"}).status_code == 201
    invite = client.post(path + "/shares", headers=owner, json={"scope": "aed_runner", "helperId": str(helper_id), "expiresInSeconds": 60, "idempotencyKey": str(uuid4())})
    assert client.post("/v1/share-sessions", headers=runner, json={"secret": invite.json["secret"]}).status_code == 201
    with psycopg.connect(dsn) as connection:
        data = connection.execute("SELECT data FROM app_state WHERE id = 1 FOR UPDATE").fetchone()[0]
        for grant in data["grants"].values():
            grant[2] = "2000-01-01T00:00:00+00:00"
        from psycopg.types.json import Jsonb
        connection.execute("UPDATE app_state SET data = %s WHERE id = 1", (Jsonb(data),))
    assert client.get(path + "/aeds", headers=runner).status_code == 403
    with psycopg.connect(dsn) as connection:
        data = connection.execute("SELECT data FROM app_state WHERE id = 1 FOR UPDATE").fetchone()[0]
        data["incidents"][str(incident_id)]["view"]["createdAt"] = "2000-01-01T00:00:00+00:00"
        connection.execute("UPDATE app_state SET data = %s WHERE id = 1", (Jsonb(data),))
    assert client.get(path + "/snapshot", headers=owner).status_code == 403
    new_incident = uuid4()
    assert client.post("/v1/incidents", headers=owner, json={"incidentId": str(new_incident), "primaryClientId": str(uuid4()), "ruleVersion": "demo-v1"}).status_code == 201
    with psycopg.connect(dsn) as connection:
        data = connection.execute("SELECT data FROM app_state WHERE id = 1").fetchone()[0]
        assert str(incident_id) not in data["incidents"]


def test_greeter_and_ems_reads_are_scoped(database):
    client, _ = database
    _, owner = session(client)
    _, greeter = session(client)
    _, ems = session(client)
    incident_id = uuid4()
    path = f"/v1/incidents/{incident_id}"
    assert client.post("/v1/incidents", headers=owner, json={"incidentId": str(incident_id), "primaryClientId": str(uuid4()), "ruleVersion": "demo-v1"}).status_code == 201
    for scope, recipient, helper_id in (("ambulance_greeter", greeter, uuid4()), ("ems_viewer", ems, None)):
        share_body = {"scope": scope, "expiresInSeconds": 60, "idempotencyKey": str(uuid4())}
        if helper_id:
            share_body["helperId"] = str(helper_id)
        invite = client.post(path + "/shares", headers=owner, json=share_body)
        assert invite.status_code == 201
        assert client.post("/v1/share-sessions", headers=recipient, json={"secret": invite.json["secret"]}).status_code == 201
    assert client.get(path + "/snapshot", headers=greeter).status_code == 200
    assert client.get(path + "/snapshot", headers=ems).status_code == 200
    assert client.get(path + "/handoff/events", headers=greeter).status_code == 403
    assert client.get(path + "/handoff/events", headers=ems).status_code == 200
    assert client.patch(path, headers=ems, json={"status": "closed", "expectedStateRevision": 0}).status_code == 403
