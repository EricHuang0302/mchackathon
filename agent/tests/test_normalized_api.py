"""Synthetic end-to-end checks for the normalized Flask/PostgreSQL boundary."""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID, uuid4

import psycopg
import pytest
from cryptography.fernet import Fernet

from app.api.http import create_app
from app.services.incident.access import resolve_principal
from app.services.incident.clock import FixedClock
from app.services.incident.ingestion import IncidentEventService
from app.services.incident.scene_snapshot import project_scene_snapshot
from app.services.postgres_data import apply_migrations
from app.services.postgres_data.aed import PostgresAedCatalogRepository
from app.services.postgres_data.retention import PostgresRetentionService
from app.services.postgres_data.uow import PostgresUnitOfWork
from data.aed.models import SourceDescriptor
from tests.aed.conftest import make_record


@pytest.fixture(scope="module")
def dsn() -> str:
    value = os.getenv("NORMALIZED_API_TEST_DSN")
    if not value:
        pytest.skip("Set NORMALIZED_API_TEST_DSN to a dedicated synthetic PostgreSQL database")
    apply_migrations(value)
    return value


@pytest.fixture
def client(monkeypatch, dsn):
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("LOCAL_INVITE_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("INCIDENT_BACKEND", "normalized")
    monkeypatch.setenv("ENABLE_UNREVIEWED_DEMO_RULES", "1")
    app = create_app()
    app.testing = True
    return app.test_client()


def session(client):
    response = client.post("/v1/sessions")
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json['sessionToken']}"}


def incident(client, auth):
    incident_id, client_id = str(uuid4()), str(uuid4())
    response = client.post("/v1/incidents", headers=auth, json={
        "incidentId": incident_id, "primaryClientId": client_id, "ruleVersion": "demo-v1",
    })
    assert response.status_code == 201, response.json
    return incident_id, client_id


def observation(key, value, *, confirmation="user_confirmed"):
    return {
        "observationId": str(uuid4()), "key": key, "value": value,
        "source": "manual_report", "observedAt": datetime.now(timezone.utc).isoformat(),
        "confirmation": confirmation, "evidenceEventIds": [],
    }


def test_events_snapshots_handoff_rules_and_scope(client):
    primary, greeter, ems, stranger = (session(client) for _ in range(4))
    incident_id, client_id = incident(client, primary)
    other_id, _ = incident(client, stranger)
    base = f"/v1/incidents/{incident_id}"
    assert client.get(base + "/snapshot").status_code == 401
    assert client.get(base + "/snapshot", headers=stranger).status_code == 403
    assert client.get(f"/v1/incidents/{other_id}/snapshot", headers=primary).status_code == 403

    event = {
        "eventId": str(uuid4()), "type": "action.reported", "detail": {"action": "synthetic_action"},
        "clientId": client_id, "clientInstanceId": str(uuid4()), "clientSequence": 1,
        "clientTime": datetime.now(timezone.utc).isoformat(), "authorityEpoch": 1,
        "stateRevision": 0, "modeRevision": 0, "ruleVersion": "demo-v1",
    }
    first = client.post(base + "/event-batches", headers=primary, json={"events": [event]})
    assert first.status_code == 200, first.json
    assert first.json["acknowledgements"][0]["status"] == "accepted"
    retry = client.post(base + "/event-batches", headers=primary, json={"events": [event]})
    assert retry.json["acknowledgements"][0]["status"] == "duplicate"
    reused_sequence = client.post(base + "/event-batches", headers=primary, json={
        "events": [{**event, "eventId": str(uuid4())}],
    })
    assert reused_sequence.status_code == 200
    assert reused_sequence.json["acknowledgements"][0]["status"] == "conflict"
    assert reused_sequence.json["acknowledgements"][0]["code"] == "invalid_input"
    mode = client.post(base + "/event-batches", headers=primary, json={
        "events": [{**event, "eventId": str(uuid4()), "clientSequence": 2,
                    "type": "mode.changed", "detail": {"interactionMode": "on_call", "reason": "dial_started"},
                    "modeRevision": 1}],
    })
    assert mode.status_code == 200, mode.json
    assert mode.json["acknowledgements"][0]["status"] == "accepted"
    assert mode.json["modeRevision"] == 1
    late_mode = client.post(base + "/event-batches", headers=primary, json={
        "events": [{**event, "eventId": str(uuid4()), "clientSequence": 3,
                    "type": "mode.changed", "detail": {"interactionMode": "voice_guidance", "reason": "user_reports_call_ended_or_failed"},
                    "modeRevision": 1}],
    })
    assert late_mode.json["acknowledgements"][0]["code"] == "stale_revision"

    body = {
        "observations": [observation("patient.breathing", True)],
        "expectedSnapshotRevision": 1, "idempotencyKey": str(uuid4()),
    }
    saved = client.post(base + "/scene-observations", headers=primary, json=body)
    assert saved.status_code == 200, saved.json
    assert client.post(base + "/scene-observations", headers=primary, json=body).json == saved.json
    stale = dict(body, idempotencyKey=str(uuid4()), expectedSnapshotRevision=0)
    assert client.post(base + "/scene-observations", headers=primary, json=stale).status_code == 409

    snapshot = client.get(base + "/snapshot", headers=primary).json
    assert snapshot["sections"]["patientCondition"]
    assert snapshot["observations"][0]["source"] == "user_report"
    assert snapshot["observations"][0]["confirmation"] == "confirmed"
    assert snapshot["snapshotRevision"] == saved.json["snapshotRevision"]

    helper_id = str(uuid4())
    for role, auth, helper in [("ambulance_greeter", greeter, helper_id), ("ems_viewer", ems, None)]:
        share = client.post(base + "/shares", headers=primary, json={
            "scope": role, "helperId": helper, "expiresInSeconds": 300,
            "idempotencyKey": str(uuid4()),
        })
        assert share.status_code == 201, share.json
        assert client.post("/v1/share-sessions", headers=auth, json={"secret": share.json["secret"]}).status_code == 201
    assert client.get(base + "/snapshot", headers=greeter).json["snapshotRevision"] == snapshot["snapshotRevision"]
    assert client.get(base + "/handoff", headers=greeter).status_code == 403
    handoff = client.get(base + "/handoff", headers=ems)
    assert handoff.status_code == 200, handoff.json
    assert handoff.json["snapshot"]["snapshotRevision"] == handoff.json["mist"]["snapshotRevision"]
    assert handoff.json["mist"]["signs"]

    rules = client.post(base + "/rule-evaluations", headers=primary, json={
        "expectedStateRevision": 0, "expectedModeRevision": 1,
        "trigger": {"type": "observation"}, "observations": [], "timers": [],
    })
    assert rules.status_code == 200, rules.json
    assert rules.json["clinicalReviewRequired"] is True
    assert rules.json["reviewStatus"] == "unreviewed_demo"
    assert client.post(base + "/rule-evaluations", headers=primary, json={
        "expectedStateRevision": 0, "expectedModeRevision": 0,
        "trigger": {"type": "observation"}, "observations": [], "timers": [],
    }).status_code == 409
    assert client.post(base + "/rule-evaluations", headers=greeter, json={
        "expectedStateRevision": 0, "expectedModeRevision": 0,
        "trigger": {"type": "observation"}, "observations": [], "timers": [],
    }).status_code == 403


def test_demo_rule_gate_is_closed_by_default(client, monkeypatch):
    primary = session(client)
    incident_id, _ = incident(client, primary)
    monkeypatch.delenv("ENABLE_UNREVIEWED_DEMO_RULES")
    response = client.post(f"/v1/incidents/{incident_id}/rule-evaluations", headers=primary, json={
        "expectedStateRevision": 0, "expectedModeRevision": 0,
        "trigger": {"type": "observation"}, "observations": [], "timers": [],
    })
    assert response.status_code == 503
    assert response.json["error"]["code"] == "unavailable"


def test_aed_unavailable_reassigns_once(client, dsn):
    primary, runner = session(client), session(client)
    incident_id, _ = incident(client, primary)
    helper_id = str(uuid4())
    now = datetime.now(timezone.utc)
    records = [
        replace(make_record(name, latitude=lat, longitude=lng, source_updated_at=now), dataset_version="api-test-v1")
        for name, lat, lng in [("near", 25.0331, 121.5651), ("next", 25.0333, 121.5653)]
    ]
    PostgresAedCatalogRepository(dsn).replace_dataset(
        SourceDescriptor("synthetic-demo", "https://example.invalid/aed", "api-test-v1", now),
        records, imported_at=now,
    )
    base = f"/v1/incidents/{incident_id}"
    location = client.post(base + "/scene-observations", headers=primary, json={
        "observations": [observation("location.coordinates", {"latitude": 25.033, "longitude": 121.565})],
        "expectedSnapshotRevision": 0, "idempotencyKey": str(uuid4()),
    })
    assert location.status_code == 200, location.json
    assert client.post(base + "/aed-assignments", headers=primary, json={
        "helperId": helper_id, "expectedStateRevision": 0,
    }).status_code == 403
    share = client.post(base + "/shares", headers=primary, json={
        "scope": "aed_runner", "helperId": helper_id,
        "expiresInSeconds": 300, "idempotencyKey": str(uuid4()),
    })
    assert client.post("/v1/share-sessions", headers=runner, json={"secret": share.json["secret"]}).status_code == 201
    assert client.get(base + "/snapshot", headers=runner).status_code == 403
    assert client.get(base + "/handoff", headers=runner).status_code == 403
    assert client.get(base + "/aeds", headers=runner).status_code == 200
    assigned = client.post(base + "/aed-assignments", headers=primary, json={
        "helperId": helper_id, "expectedStateRevision": 0,
    })
    assert assigned.status_code == 201, assigned.json
    assert assigned.json["outcome"] == "assigned"
    assert assigned.json["estimate"]["outbound"]["routeBased"] is False
    assignment_path = base + f"/helpers/{helper_id}/aed-assignment"
    current = client.get(assignment_path, headers=runner)
    assert current.status_code == 200, current.json
    assert current.json["assignmentRevision"] == assigned.json["assignmentRevision"]
    assert current.json["destination"]["estimateSource"] == "straight_line"
    assert current.json["destination"]["walkingMeters"] is None
    assert current.json["destination"]["etaSeconds"] is None
    assert client.get(assignment_path, headers=primary).status_code == 200
    assert client.get(base + f"/helpers/{uuid4()}/aed-assignment", headers=runner).status_code == 403
    delivered = client.post(base + f"/helpers/{helper_id}/updates", headers=runner, json={
        "updateId": str(uuid4()), "expectedAssignmentRevision": 0,
        "status": "delivered", "reportedAt": datetime.now(timezone.utc).isoformat(),
    })
    assert delivered.status_code == 200, delivered.json
    latest = client.get(assignment_path, headers=primary)
    assert latest.json["helperStatus"] == "delivered"
    assert latest.json["helperStatusUpdatedAt"] is not None
    report = {
        "reportId": str(uuid4()), "aedId": assigned.json["aedId"],
        "reasonCode": "synthetic_cabinet_locked",
        "expectedAssignmentRevision": assigned.json["assignmentRevision"],
        "reportedAt": datetime.now(timezone.utc).isoformat(),
    }
    path = base + f"/helpers/{helper_id}/aed-unavailability-reports"
    assert client.post(path, headers=primary, json=report).status_code == 403
    changed = client.post(path, headers=runner, json=report)
    assert changed.status_code == 200, changed.json
    assert changed.json["outcome"] == "reassigned"
    assert changed.json["aedId"] != assigned.json["aedId"]
    assert changed.json["assignmentRevision"] == assigned.json["assignmentRevision"] + 1
    duplicate = client.post(path, headers=runner, json=report)
    assert duplicate.json["assignmentRevision"] == changed.json["assignmentRevision"]
    assert duplicate.json["deduplicated"] is True
    repeated = client.post(path, headers=runner, json={**report, "reportId": str(uuid4())})
    assert repeated.status_code == 200
    assert repeated.json["outcome"] == "duplicate_report"
    assert repeated.json["assignmentRevision"] == changed.json["assignmentRevision"]


def test_normalized_live_reconnect_stays_muted_on_call(client, dsn):
    from app.api.auth import LocalSessionStore
    from app.api.errors import ApiError
    from app.api.live import LiveSession
    from app.api.normalized import NormalizedIncidentService

    primary = session(client)
    incident_id, client_id = incident(client, primary)
    instance_id = str(uuid4())
    mode_event = {
        "eventId": str(uuid4()), "type": "mode.changed",
        "detail": {"interactionMode": "on_call", "reason": "dial_started"},
        "clientId": client_id, "clientInstanceId": instance_id, "clientSequence": 1,
        "clientTime": datetime.now(timezone.utc).isoformat(), "authorityEpoch": 1,
        "stateRevision": 0, "modeRevision": 1, "ruleVersion": "demo-v1",
    }
    changed = client.post(f"/v1/incidents/{incident_id}/event-batches", headers=primary, json={"events": [mode_event]})
    assert changed.json["acknowledgements"][0]["status"] == "accepted"
    providers = []

    def no_provider(*_args):
        providers.append(True)
        raise AssertionError("No voice provider may start during a call")

    service = NormalizedIncidentService(dsn, os.environ["LOCAL_INVITE_KEY"])
    token = primary["Authorization"].split(" ", 1)[1]
    for _ in range(2):
        live = LiveSession(service, LocalSessionStore(dsn), no_provider)
        hello = {
            "protocolVersion": 1, "messageId": str(uuid4()), "incidentId": incident_id,
            "clientId": client_id, "clientInstanceId": str(uuid4()),
            "clientSequence": 0, "clientTime": datetime.now(timezone.utc).isoformat(),
            "authorityEpoch": 1, "stateRevision": 0, "modeRevision": 1,
            "payload": {"type": "session.hello"},
        }
        ready = live.authenticate({"type": "auth", "token": token, "envelope": hello}, UUID(incident_id))
        assert ready["interactionMode"] == "on_call"
        assert ready["voiceAllowed"] is False and ready["resumeRequired"] is True
        with pytest.raises(ApiError) as error:
            live.receive({**hello, "messageId": str(uuid4()), "clientSequence": 1,
                          "payload": {"type": "resume.request"}})
        assert error.value.status == 403
        live.close()
    assert providers == []


def test_unit_of_work_rolls_back_events_and_snapshot(dsn):
    incident_id, client_id = str(uuid4()), str(uuid4())
    now = datetime.now(timezone.utc)
    with PostgresUnitOfWork(dsn) as uow:
        IncidentEventService(uow.events, uow.incidents, FixedClock(now)).register_incident(
            incident_id=incident_id, owner_uid="synthetic-owner", primary_client_id=client_id,
            rule_version="demo-v1",
        )
        uow.snapshots.put(project_scene_snapshot(uow.incidents.require(incident_id), (), now=now))
    payload = {
        "eventId": str(uuid4()), "type": "action.reported", "detail": {"action": "synthetic"},
        "clientId": client_id, "clientInstanceId": str(uuid4()), "clientSequence": 1,
        "clientTime": now.isoformat(), "authorityEpoch": 0,
        "stateRevision": 0, "modeRevision": 0, "ruleVersion": "demo-v1",
    }
    with pytest.raises(RuntimeError, match="synthetic failure"):
        with PostgresUnitOfWork(dsn) as uow:
            uow.lock_incident(incident_id)
            service = IncidentEventService(uow.events, uow.incidents, FixedClock(now))
            principal = resolve_principal(
                incident_id=incident_id, owner_uid="synthetic-owner", uid="synthetic-owner",
                now=now, grants=uow.grants,
            )
            result = service.ingest_batch(incident_id, [payload], principal=principal)
            uow.snapshots.put(project_scene_snapshot(result.incident, uow.events.list_events(incident_id), now=now))
            raise RuntimeError("synthetic failure")
    with psycopg.connect(dsn) as connection:
        assert connection.execute("SELECT count(*) FROM incident_events WHERE incident_id = %s", (incident_id,)).fetchone()[0] == 0
        assert connection.execute("SELECT snapshot_revision FROM scene_snapshots WHERE incident_id = %s", (incident_id,)).fetchone()[0] == 0
    assert PostgresRetentionService(dsn).purge().operation_keys >= 0
