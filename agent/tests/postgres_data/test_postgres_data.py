"""Repository codecs, migrations, and optional PostgreSQL integration checks."""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from importlib.resources import files
from uuid import uuid4

import psycopg
import pytest
from psycopg import conninfo, sql

from data.aed.models import (
    AedRecord,
    GeoPoint,
    OpeningHours,
    OpeningWindow,
    SourceDescriptor,
)

from app.services.aed.assignment import (
    AedAssignment,
    AssignmentConflict,
    AssignmentStatus,
    ReassignmentOutcome,
    ReassignmentResult,
)
from app.services.incident.access import AccessGrant
from app.services.incident.errors import INVALID_INPUT, STALE_REVISION, ServiceError
from app.services.incident.event_store import DuplicateEventError
from app.services.incident.models import EventEnvelope, IncidentRecord, StoredEvent
from app.services.incident.scene_snapshot import project_scene_snapshot
from app.services.postgres_data import (
    AccessInvitation,
    PostgresAedCatalogRepository,
    PostgresAssignmentStore,
    PostgresEventStore,
    PostgresGrantStore,
    PostgresIncidentStore,
    PostgresInvitationStore,
    PostgresRetentionService,
    PostgresSceneSnapshotStore,
    apply_migrations,
)
from app.services.postgres_data.aed import (
    _record_from_data,
    _record_to_data,
    _result_from_data,
    _result_to_data,
)


UTC = timezone.utc


def test_packaged_migration_is_forward_only_and_constrained():
    migration = (
        files("app.services.postgres_data")
        .joinpath("migrations/001_normalized_services.sql")
        .read_text(encoding="utf-8")
    )
    assert "DROP TABLE" not in migration.upper()
    assert "REFERENCES incidents" in migration
    assert "UNIQUE (incident_id, server_sequence)" in migration
    assert "access_grants_authorization_idx" in migration
    assert "aed_datasets_one_active_source_idx" in migration


def test_assignment_result_codec_preserves_revision_and_idempotency_fields():
    assigned_at = datetime(2026, 9, 19, tzinfo=UTC)
    assignment = AedAssignment(
        incident_id="incident-1",
        helper_id="helper-1",
        aed_id=None,
        assignment_revision=3,
        assigned_at=assigned_at,
        status=AssignmentStatus.NO_CANDIDATE,
        previous_aed_id="aed-2",
    )
    value = ReassignmentResult(
        outcome=ReassignmentOutcome.NO_CANDIDATE,
        incident_id="incident-1",
        assignment=assignment,
        excluded_aed_ids=("aed-1", "aed-2"),
        detail="no remaining candidate",
        report_id="report-1",
        deduplicated=True,
    )
    assert _result_from_data(_result_to_data(value)) == value


def test_aed_codec_preserves_location_id_and_partial_opening_hours():
    at = datetime(2026, 9, 19, tzinfo=UTC)
    record = AedRecord(
        stable_id="mohw:aed-1",
        source_id="aed-1",
        source_location_id="location-1",
        source_system="mohw-taiwan-aed",
        name="Synthetic AED",
        point=GeoPoint(25.0, 121.5),
        address="Synthetic address",
        opening_hours=OpeningHours(
            known=True,
            windows=(OpeningWindow(weekday=0, start_minute=480, end_minute=1080),),
            unknown_weekdays=(6,),
            raw="Mon 08:00-18:00; Sun unknown",
        ),
        access_notes="Synthetic access note",
        access_notes_known=True,
        source_url="https://example.invalid/aed.csv",
        source_updated_at=at,
        ingested_at=at,
        dataset_version="v1",
    )

    assert _record_from_data(_record_to_data(record)) == record


def test_empty_aed_dataset_fails_before_database_connection():
    descriptor = SourceDescriptor(
        source_system="synthetic-test",
        source_url="https://example.invalid/aed.csv",
        dataset_version="v1",
        retrieved_at=datetime(2026, 9, 19, tzinfo=UTC),
    )

    with pytest.raises(ServiceError) as error:
        PostgresAedCatalogRepository("postgresql://not-used").replace_dataset(
            descriptor,
            (),
            imported_at=descriptor.retrieved_at,
        )

    assert (error.value.code, error.value.reason) == (
        INVALID_INPUT,
        "empty_aed_dataset",
    )


@pytest.fixture
def postgres_dsn():
    base_dsn = os.getenv("PG_TEST_DSN")
    if not base_dsn:
        pytest.skip("Set PG_TEST_DSN for normalized PostgreSQL integration checks")
    schema = f"ws5_test_{uuid4().hex}"
    with psycopg.connect(base_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    parameters = conninfo.conninfo_to_dict(base_dsn)
    existing_options = parameters.get("options", "")
    parameters["options"] = f"{existing_options} -c search_path={schema}".strip()
    scoped_dsn = conninfo.make_conninfo(**parameters)
    try:
        yield scoped_dsn
    finally:
        with psycopg.connect(base_dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )


def _incident(*, expires_at: datetime | None = None) -> IncidentRecord:
    created_at = datetime(2026, 9, 19, tzinfo=UTC)
    return IncidentRecord(
        incident_id=str(uuid4()),
        owner_uid="owner-1",
        primary_client_id="client-1",
        rule_version="demo-v1",
        created_at=created_at,
        updated_at=created_at,
        expires_at=expires_at or created_at + timedelta(days=1),
    )


def _event(record: IncidentRecord) -> StoredEvent:
    at = record.created_at + timedelta(seconds=1)
    return StoredEvent(
        incident_id=record.incident_id,
        envelope=EventEnvelope(
            event_id=str(uuid4()),
            type="action.reported",
            detail={"action": "synthetic_action"},
            client_id=record.primary_client_id,
            client_instance_id="instance-1",
            client_sequence=1,
            client_time=at,
            authority_epoch=record.authority_epoch,
            state_revision=record.state_revision,
            mode_revision=record.mode_revision,
            rule_version=record.rule_version,
            source="manual_report",
        ),
        actor_id=record.owner_uid,
        actor_role="primary",
        server_time=at,
        server_sequence=1,
        expires_at=record.expires_at,
    )


def test_postgres_repositories_preserve_constraints_and_stale_writes(postgres_dsn):
    assert apply_migrations(postgres_dsn) == ("001", "002")
    assert apply_migrations(postgres_dsn) == ()

    incidents = PostgresIncidentStore(postgres_dsn)
    events = PostgresEventStore(postgres_dsn)
    snapshots = PostgresSceneSnapshotStore(postgres_dsn)
    invitations = PostgresInvitationStore(postgres_dsn)
    grants = PostgresGrantStore(postgres_dsn)

    record = _incident()
    assert incidents.create(record) == record
    advanced = replace(
        record,
        state_revision=2,
        updated_at=record.updated_at + timedelta(seconds=2),
    )
    assert incidents.put(advanced) == advanced
    with pytest.raises(ServiceError) as stale:
        incidents.put(record)
    assert stale.value.code == STALE_REVISION

    stored_event = _event(advanced)
    events.append(stored_event)
    assert events.get(record.incident_id, stored_event.event_id) == stored_event
    assert events.list_events(record.incident_id) == (stored_event,)
    with pytest.raises(DuplicateEventError):
        events.append(stored_event)

    first_snapshot = project_scene_snapshot(
        advanced, (stored_event,), now=stored_event.server_time
    )
    assert snapshots.put(first_snapshot) == first_snapshot
    stale_snapshot = replace(first_snapshot, snapshot_revision=0)
    assert snapshots.put(stale_snapshot) == first_snapshot

    invite = AccessInvitation(
        invitation_id="invite-1",
        incident_id=record.incident_id,
        secret_hash="a" * 64,
        encrypted_secret=b"encrypted-secret",
        scope="ems_viewer",
        idempotency_key="key-1",
        created_at=record.created_at,
        expires_at=record.created_at + timedelta(minutes=5),
    )
    assert invitations.put(invite) == invite
    retry = replace(
        invite,
        invitation_id="invite-retry",
        secret_hash="b" * 64,
        encrypted_secret=b"different-ciphertext",
        created_at=invite.created_at + timedelta(minutes=1),
        expires_at=invite.expires_at + timedelta(minutes=1),
    )
    assert invitations.put(retry) == invite
    conflicting = replace(invite, invitation_id="invite-2", scope="aed_runner", helper_id="helper-1")
    with pytest.raises(ServiceError) as reused:
        invitations.put(conflicting)
    assert reused.value.code == INVALID_INPUT

    grant = AccessGrant(
        grant_id="grant-1",
        incident_id=record.incident_id,
        uid="viewer-1",
        scope="ems_viewer",
        expires_at=record.created_at + timedelta(minutes=5),
    )
    assert grants.put(grant) == grant
    assert grants.get(record.incident_id, "viewer-1") == grant


def test_postgres_assignment_cas_and_retention(postgres_dsn):
    apply_migrations(postgres_dsn)
    incidents = PostgresIncidentStore(postgres_dsn)
    record = _incident(expires_at=datetime(2026, 9, 20, tzinfo=UTC))
    incidents.create(record)
    catalog = PostgresAedCatalogRepository(postgres_dsn)
    descriptor = SourceDescriptor(
        source_system="synthetic-test",
        source_url="https://example.invalid/aed.csv",
        dataset_version="v1",
        retrieved_at=record.created_at,
    )
    aed = AedRecord(
        stable_id="aed-1",
        source_id="source-1",
        source_location_id="location-1",
        source_system=descriptor.source_system,
        name="Synthetic AED",
        point=GeoPoint(25.0, 121.5),
        address="Synthetic address",
        opening_hours=OpeningHours(
            known=True,
            windows=(OpeningWindow(weekday=0, start_minute=480, end_minute=1080),),
            unknown_weekdays=(6,),
            raw="Mon 08:00-18:00; Sun unknown",
        ),
        access_notes=None,
        access_notes_known=False,
        source_url=descriptor.source_url,
        source_updated_at=None,
        ingested_at=record.created_at,
        dataset_version=descriptor.dataset_version,
    )
    assert catalog.replace_dataset(
        descriptor, (aed,), imported_at=record.created_at
    ) == 1
    assert catalog.list_active() == (aed,)
    store = PostgresAssignmentStore(postgres_dsn)
    assignment = AedAssignment(
        incident_id=record.incident_id,
        helper_id="helper-1",
        aed_id=None,
        assignment_revision=1,
        assigned_at=record.created_at,
        status=AssignmentStatus.NO_CANDIDATE,
    )
    result = ReassignmentResult(
        outcome=ReassignmentOutcome.NO_CANDIDATE,
        incident_id=record.incident_id,
        assignment=assignment,
        excluded_aed_ids=("aed-1",),
        report_id="report-1",
    )
    store.commit_assignment(
        record.incident_id,
        expected_revision=None,
        assignment=assignment,
        exclude_aed_id="aed-1",
        report_id="report-1",
        result=result,
    )
    assert store.read_state(record.incident_id).assignment == assignment
    assert store.get_report_result(record.incident_id, "report-1") == result
    with pytest.raises(AssignmentConflict) as conflict:
        store.commit_assignment(
            record.incident_id,
            expected_revision=None,
            assignment=assignment,
        )
    assert getattr(conflict.value, "reason_code", None) == "revision_changed"

    cleanup = PostgresRetentionService(postgres_dsn).purge(
        datetime(2026, 9, 21, tzinfo=UTC)
    )
    assert cleanup.incidents == 1
    assert incidents.get(record.incident_id) is None
