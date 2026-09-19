"""PostgreSQL adapters for incidents, events, and scene projections."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg

from .connection import ConnectionBoundRepository
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb

from app.services.incident.clock import utc
from app.services.incident.errors import UNAVAILABLE, ServiceError
from app.services.incident.event_store import (
    DuplicateEventError,
    EventStore,
    IncidentStore,
)
from app.services.incident.models import (
    EventEnvelope,
    IncidentRecord,
    Provenance,
    ReportedAction,
    SceneSnapshot,
    SnapshotField,
    StoredEvent,
)


def _unavailable(exc: psycopg.Error) -> ServiceError:
    return ServiceError(UNAVAILABLE, "postgres_unavailable", detail={"type": type(exc).__name__})


class PostgresIncidentStore(ConnectionBoundRepository, IncidentStore):
    """Normalized persistence for canonical incident state."""

    def create(self, record: IncidentRecord) -> IncidentRecord:
        try:
            with self._connection_scope() as connection:
                connection.execute(
                    """
                    INSERT INTO incidents (
                        incident_id, owner_uid, primary_client_id, rule_version,
                        status, interaction_mode, mode_revision, clinical_state,
                        guidance_paused, state_revision, authority_epoch, call_status,
                        acknowledged_client_sequences, created_at, updated_at, expires_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    ) ON CONFLICT (incident_id) DO NOTHING
                    """,
                    _incident_values(record),
                )
                stored = _select_incident(connection, record.incident_id)
        except psycopg.Error as exc:
            raise _unavailable(exc) from None
        if stored is None:
            raise ServiceError(UNAVAILABLE, "incident_create_failed")
        if stored.owner_uid != record.owner_uid:
            from app.services.incident.errors import INVALID_INPUT

            raise ServiceError(
                INVALID_INPUT,
                "incident_owned_by_another_uid",
                detail={"incidentId": record.incident_id},
            )
        if (
            stored.primary_client_id != record.primary_client_id
            or stored.rule_version != record.rule_version
        ):
            from app.services.incident.errors import INVALID_INPUT

            raise ServiceError(
                INVALID_INPUT,
                "incident_registration_mismatch",
                detail={
                    "incidentId": record.incident_id,
                    "primaryClientId": stored.primary_client_id,
                    "ruleVersion": stored.rule_version,
                },
            )
        return stored

    def get(self, incident_id: str) -> IncidentRecord | None:
        try:
            with self._connection_scope() as connection:
                return _select_incident(connection, incident_id)
        except psycopg.Error as exc:
            raise _unavailable(exc) from None

    def put(self, record: IncidentRecord) -> IncidentRecord:
        try:
            with self._connection_scope() as connection:
                current = _select_incident(connection, record.incident_id, for_update=True)
                if current is None:
                    raise ServiceError(
                        UNAVAILABLE,
                        "incident_update_missing",
                        detail={"incidentId": record.incident_id},
                    )
                if current.state_revision > record.state_revision:
                    from app.services.incident.errors import STALE_REVISION

                    raise ServiceError(
                        STALE_REVISION,
                        "stored_revision_is_newer",
                        detail={
                            "storedStateRevision": current.state_revision,
                            "receivedStateRevision": record.state_revision,
                        },
                    )
                row = connection.execute(
                    """
                    UPDATE incidents SET
                        owner_uid = %s, primary_client_id = %s, rule_version = %s,
                        status = %s, interaction_mode = %s, mode_revision = %s,
                        clinical_state = %s, guidance_paused = %s,
                        state_revision = %s, authority_epoch = %s, call_status = %s,
                        acknowledged_client_sequences = %s, created_at = %s,
                        updated_at = %s, expires_at = %s
                    WHERE incident_id = %s
                    RETURNING incident_id, owner_uid, primary_client_id, rule_version,
                        created_at, updated_at, expires_at, status, interaction_mode,
                        mode_revision, clinical_state, guidance_paused, state_revision,
                        authority_epoch, call_status, acknowledged_client_sequences
                    """,
                    _incident_values(record)[1:] + (record.incident_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise _unavailable(exc) from None
        return _incident_from_row(row)


class PostgresEventStore(ConnectionBoundRepository, EventStore):
    """Append-only event rows with incident-scoped sequence constraints."""

    def append(self, event: StoredEvent) -> StoredEvent:
        envelope = event.envelope
        try:
            with self._connection_scope() as connection:
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (event.incident_id,),
                )
                duplicate = connection.execute(
                    "SELECT 1 FROM incident_events WHERE incident_id = %s AND event_id = %s",
                    (event.incident_id, event.event_id),
                ).fetchone()
                if duplicate is not None:
                    raise DuplicateEventError(event.incident_id, event.event_id)
                expected = connection.execute(
                    "SELECT COALESCE(MAX(server_sequence), 0) + 1 FROM incident_events WHERE incident_id = %s",
                    (event.incident_id,),
                ).fetchone()[0]
                if event.server_sequence != expected:
                    raise ServiceError(
                        UNAVAILABLE,
                        "sequence_out_of_band",
                        detail={"expected": expected, "received": event.server_sequence},
                    )
                connection.execute(
                    """
                    INSERT INTO incident_events (
                        incident_id, event_id, event_type, detail, source, actor_id,
                        actor_role, client_id, client_instance_id, client_sequence,
                        client_time, client_time_uncertain, server_time, server_sequence,
                        authority_epoch, state_revision, mode_revision, rule_version, expires_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        event.incident_id,
                        envelope.event_id,
                        envelope.type,
                        Jsonb(envelope.detail),
                        envelope.source,
                        event.actor_id,
                        event.actor_role,
                        envelope.client_id,
                        envelope.client_instance_id,
                        envelope.client_sequence,
                        envelope.client_time,
                        envelope.client_time_uncertain,
                        event.server_time,
                        event.server_sequence,
                        envelope.authority_epoch,
                        envelope.state_revision,
                        envelope.mode_revision,
                        envelope.rule_version,
                        event.expires_at,
                    ),
                )
        except DuplicateEventError:
            raise
        except UniqueViolation:
            if self.get(event.incident_id, event.event_id) is not None:
                raise DuplicateEventError(event.incident_id, event.event_id) from None
            raise ServiceError(UNAVAILABLE, "event_sequence_conflict") from None
        except psycopg.Error as exc:
            raise _unavailable(exc) from None
        return event

    def _get_by_client_sequence(
        self, incident_id: str, client_id: str, client_instance_id: str, client_sequence: int
    ) -> StoredEvent | None:
        try:
            with self._connection_scope() as connection:
                row = connection.execute(
                    f"SELECT {_EVENT_COLUMNS} FROM incident_events WHERE incident_id = %s AND client_id = %s AND client_instance_id = %s AND client_sequence = %s",
                    (incident_id, client_id, client_instance_id, client_sequence),
                ).fetchone()
        except psycopg.Error as exc:
            raise _unavailable(exc) from None
        return _event_from_row(row) if row is not None else None

    def get(self, incident_id: str, event_id: str) -> StoredEvent | None:
        try:
            with self._connection_scope() as connection:
                row = connection.execute(
                    f"SELECT {_EVENT_COLUMNS} FROM incident_events WHERE incident_id = %s AND event_id = %s",
                    (incident_id, event_id),
                ).fetchone()
        except psycopg.Error as exc:
            raise _unavailable(exc) from None
        return _event_from_row(row) if row else None

    def list_events(
        self,
        incident_id: str,
        *,
        after_sequence: int | None = None,
        limit: int | None = None,
    ) -> tuple[StoredEvent, ...]:
        if limit is not None and limit < 0:
            from app.services.incident.errors import INVALID_INPUT

            raise ServiceError(INVALID_INPUT, "negative_limit", detail={"limit": limit})
        query = f"SELECT {_EVENT_COLUMNS} FROM incident_events WHERE incident_id = %s"
        params: list[Any] = [incident_id]
        if after_sequence is not None:
            query += " AND server_sequence > %s"
            params.append(after_sequence)
        query += " ORDER BY server_sequence"
        if limit is not None:
            query += " LIMIT %s"
            params.append(limit)
        try:
            with self._connection_scope() as connection:
                rows = connection.execute(query, params).fetchall()
        except psycopg.Error as exc:
            raise _unavailable(exc) from None
        return tuple(_event_from_row(row) for row in rows)

    def next_sequence(self, incident_id: str) -> int:
        try:
            with self._connection_scope() as connection:
                return int(
                    connection.execute(
                        "SELECT COALESCE(MAX(server_sequence), 0) + 1 FROM incident_events WHERE incident_id = %s",
                        (incident_id,),
                    ).fetchone()[0]
                )
        except psycopg.Error as exc:
            raise _unavailable(exc) from None

    def count(self, incident_id: str) -> int:
        try:
            with self._connection_scope() as connection:
                return int(
                    connection.execute(
                        "SELECT count(*) FROM incident_events WHERE incident_id = %s",
                        (incident_id,),
                    ).fetchone()[0]
                )
        except psycopg.Error as exc:
            raise _unavailable(exc) from None

    def purge_expired(self, now: datetime) -> int:
        try:
            with self._connection_scope() as connection:
                cursor = connection.execute(
                    "DELETE FROM incident_events WHERE expires_at <= %s", (now,)
                )
                return cursor.rowcount
        except psycopg.Error as exc:
            raise _unavailable(exc) from None


class PostgresSceneSnapshotStore(ConnectionBoundRepository):
    """Persist the canonical scene projection and its replay boundary."""

    def get(self, incident_id: str) -> SceneSnapshot | None:
        try:
            with self._connection_scope() as connection:
                row = connection.execute(
                    "SELECT payload FROM scene_snapshots WHERE incident_id = %s",
                    (incident_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise _unavailable(exc) from None
        return _snapshot_from_payload(row[0]) if row else None

    def put(self, snapshot: SceneSnapshot) -> SceneSnapshot:
        if snapshot.expires_at is None:
            raise ValueError("persistent snapshots require expires_at")
        try:
            with self._connection_scope() as connection:
                row = connection.execute(
                    """
                    INSERT INTO scene_snapshots (
                        incident_id, snapshot_revision, generated_through_revision,
                        generated_through_sequence, generated_through_event_id,
                        payload, updated_at, expires_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (incident_id) DO UPDATE SET
                        snapshot_revision = EXCLUDED.snapshot_revision,
                        generated_through_revision = EXCLUDED.generated_through_revision,
                        generated_through_sequence = EXCLUDED.generated_through_sequence,
                        generated_through_event_id = EXCLUDED.generated_through_event_id,
                        payload = EXCLUDED.payload,
                        updated_at = EXCLUDED.updated_at,
                        expires_at = EXCLUDED.expires_at
                    WHERE scene_snapshots.snapshot_revision <= EXCLUDED.snapshot_revision
                    RETURNING payload
                    """,
                    (
                        snapshot.incident_id,
                        snapshot.snapshot_revision,
                        snapshot.generated_through_revision,
                        snapshot.generated_through_sequence,
                        snapshot.generated_through_event_id,
                        Jsonb(snapshot.to_dict()),
                        snapshot.updated_at,
                        snapshot.expires_at,
                    ),
                ).fetchone()
        except psycopg.Error as exc:
            raise _unavailable(exc) from None
        if row is not None:
            return _snapshot_from_payload(row[0])
        persisted = self.get(snapshot.incident_id)
        if persisted is None:
            raise ServiceError(UNAVAILABLE, "snapshot_write_failed")
        return persisted


_INCIDENT_COLUMNS = """
incident_id, owner_uid, primary_client_id, rule_version, created_at, updated_at,
expires_at, status, interaction_mode, mode_revision, clinical_state,
guidance_paused, state_revision, authority_epoch, call_status,
acknowledged_client_sequences
"""


def _incident_values(record: IncidentRecord) -> tuple[Any, ...]:
    return (
        record.incident_id,
        record.owner_uid,
        record.primary_client_id,
        record.rule_version,
        record.status,
        record.interaction_mode,
        record.mode_revision,
        record.clinical_state,
        record.guidance_paused,
        record.state_revision,
        record.authority_epoch,
        Jsonb(record.call_status),
        Jsonb(dict(record.acknowledged_client_sequences)),
        record.created_at,
        record.updated_at,
        record.expires_at,
    )


def _select_incident(
    connection: psycopg.Connection, incident_id: str, *, for_update: bool = False
) -> IncidentRecord | None:
    suffix = " FOR UPDATE" if for_update else ""
    row = connection.execute(
        f"SELECT {_INCIDENT_COLUMNS} FROM incidents WHERE incident_id = %s{suffix}",
        (incident_id,),
    ).fetchone()
    return _incident_from_row(row) if row else None


def _incident_from_row(row: tuple[Any, ...]) -> IncidentRecord:
    return IncidentRecord(
        incident_id=row[0],
        owner_uid=row[1],
        primary_client_id=row[2],
        rule_version=row[3],
        created_at=row[4],
        updated_at=row[5],
        expires_at=row[6],
        status=row[7],
        interaction_mode=row[8],
        mode_revision=row[9],
        clinical_state=row[10],
        guidance_paused=row[11],
        state_revision=row[12],
        authority_epoch=row[13],
        call_status=row[14],
        acknowledged_client_sequences=row[15],
    )


_EVENT_COLUMNS = """
incident_id, event_id, event_type, detail, source, actor_id, actor_role,
client_id, client_instance_id, client_sequence, client_time,
client_time_uncertain, server_time, server_sequence, authority_epoch,
state_revision, mode_revision, rule_version, expires_at
"""


def _event_from_row(row: tuple[Any, ...]) -> StoredEvent:
    envelope = EventEnvelope(
        event_id=row[1],
        type=row[2],
        detail=row[3],
        source=row[4],
        client_id=row[7],
        client_instance_id=row[8],
        client_sequence=row[9],
        client_time=row[10],
        client_time_uncertain=row[11],
        authority_epoch=row[14],
        state_revision=row[15],
        mode_revision=row[16],
        rule_version=row[17],
    )
    return StoredEvent(
        incident_id=row[0],
        envelope=envelope,
        actor_id=row[5],
        actor_role=row[6],
        server_time=row[12],
        server_sequence=row[13],
        expires_at=row[18],
    )


def _optional_time(value: str | None) -> datetime | None:
    return utc(value) if value else None


def _snapshot_from_payload(payload: dict[str, Any]) -> SceneSnapshot:
    sections: dict[str, tuple[SnapshotField, ...]] = {}
    for name, values in payload["sections"].items():
        fields: list[SnapshotField] = []
        for value in values:
            source = value["provenance"]
            provenance = Provenance(
                source=source["source"],
                confirmation=source["confirmation"],
                observed_at=_optional_time(source.get("observedAt")),
                received_at=_optional_time(source.get("receivedAt")),
                evidence_event_ids=tuple(source.get("evidenceEventIds", ())),
                corrected_from_event_ids=tuple(source.get("correctedFromEventIds", ())),
                observed_time_uncertain=source.get("observedTimeUncertain", False),
            )
            fields.append(
                SnapshotField(
                    key=value["key"],
                    section=value["section"],
                    value=value.get("value"),
                    provenance=provenance,
                    freshness=value.get("freshness", "unknown"),
                    age_seconds=value.get("ageSeconds"),
                    pending_proposals=tuple(value.get("pendingProposals", ())),
                )
            )
        sections[name] = tuple(fields)
    actions = tuple(
        ReportedAction(
            action=value["action"],
            reported_at=utc(value["reportedAt"]),
            event_id=value["eventId"],
            source=value["source"],
            detail=value.get("detail", {}),
            corrected_from_event_ids=tuple(value.get("correctedFromEventIds", ())),
            retracted=value.get("retracted", False),
        )
        for value in payload.get("actionsPerformed", ())
    )
    return SceneSnapshot(
        incident_id=payload["incidentId"],
        snapshot_revision=payload["snapshotRevision"],
        updated_at=_optional_time(payload.get("updatedAt")),
        generated_through_revision=payload["generatedThroughRevision"],
        generated_through_sequence=payload["generatedThroughSequence"],
        generated_through_event_id=payload.get("generatedThroughEventId"),
        sections=sections,
        actions_performed=actions,
        expires_at=_optional_time(payload.get("expiresAt")),
    )


__all__ = [
    "PostgresEventStore",
    "PostgresIncidentStore",
    "PostgresSceneSnapshotStore",
]
