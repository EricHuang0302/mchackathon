"""Explicit retention cleanup for normalized and legacy PostgreSQL state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import psycopg
from cryptography.fernet import Fernet
from psycopg.types.json import Jsonb

from app.services.incident.errors import UNAVAILABLE, ServiceError


@dataclass(frozen=True, slots=True)
class RetentionResult:
    """Deleted row counts from one bounded cleanup transaction."""

    events: int = 0
    operation_keys: int = 0
    snapshots: int = 0
    invitations: int = 0
    grants: int = 0
    reports: int = 0
    assignments: int = 0
    incidents: int = 0
    datasets: int = 0
    legacy_incidents: int = 0
    legacy_invitations: int = 0
    legacy_grants: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "events": self.events,
            "operationKeys": self.operation_keys,
            "snapshots": self.snapshots,
            "invitations": self.invitations,
            "grants": self.grants,
            "reports": self.reports,
            "assignments": self.assignments,
            "incidents": self.incidents,
            "datasets": self.datasets,
            "legacyIncidents": self.legacy_incidents,
            "legacyInvitations": self.legacy_invitations,
            "legacyGrants": self.legacy_grants,
        }


class PostgresRetentionService:
    """Delete expired rows; authorization must still enforce expiry immediately."""

    def __init__(self, dsn: str, *, legacy_invite_key: str | None = None) -> None:
        self.dsn = dsn
        self.legacy_invite_key = legacy_invite_key

    def purge(self, now: datetime | None = None) -> RetentionResult:
        instant = now or datetime.now(timezone.utc)
        try:
            with psycopg.connect(self.dsn) as connection:
                counts = {
                    "events": _delete(connection, "incident_events", instant),
                    "operation_keys": _delete(connection, "api_operation_keys", instant),
                    "snapshots": _delete(connection, "scene_snapshots", instant),
                    "invitations": _delete(connection, "access_invitations", instant),
                    "grants": _delete(connection, "access_grants", instant),
                    "reports": _delete(connection, "aed_unavailability_reports", instant),
                    "assignments": _delete(connection, "aed_assignments", instant),
                }
                counts["incidents"] = _delete(connection, "incidents", instant)
                counts["datasets"] = connection.execute(
                    """
                    DELETE FROM aed_datasets
                    WHERE NOT active AND expires_at IS NOT NULL AND expires_at <= %s
                    """,
                    (instant,),
                ).rowcount
                legacy = self._purge_legacy(connection, instant)
        except psycopg.Error as exc:
            raise ServiceError(
                UNAVAILABLE, "postgres_unavailable", detail={"type": type(exc).__name__}
            ) from None
        return RetentionResult(**counts, **legacy)

    def _purge_legacy(
        self, connection: psycopg.Connection, now: datetime
    ) -> dict[str, int]:
        exists = connection.execute("SELECT to_regclass('app_state')").fetchone()[0]
        if exists is None or not self.legacy_invite_key:
            return {
                "legacy_incidents": 0,
                "legacy_invitations": 0,
                "legacy_grants": 0,
            }

        from app.services.postgres import _dump, _load

        row = connection.execute(
            "SELECT data FROM app_state WHERE id = 1 FOR UPDATE"
        ).fetchone()
        if row is None:
            return {
                "legacy_incidents": 0,
                "legacy_invitations": 0,
                "legacy_grants": 0,
            }
        cipher = Fernet(self.legacy_invite_key.encode())
        service = _load(row[0], cipher)
        before = (
            len(service._incidents),
            len(service._invites),
            len(service._grants),
        )
        expired_incidents = {
            incident_id
            for incident_id, record in service._incidents.items()
            if record.view.createdAt <= now - timedelta(hours=72)
        }
        for incident_id in expired_incidents:
            del service._incidents[incident_id]
        for secret_hash, invitation in list(service._invites.items()):
            if invitation[0] in expired_incidents or invitation[1].expiresAt <= now:
                del service._invites[secret_hash]
                service._invite_failures[secret_hash] = "invitation_expired"
        for key, grant in list(service._grants.items()):
            if key[1] in expired_incidents or grant[2] <= now:
                del service._grants[key]
        after = (
            len(service._incidents),
            len(service._invites),
            len(service._grants),
        )
        if before != after:
            connection.execute(
                "UPDATE app_state SET data = %s WHERE id = 1",
                (Jsonb(_dump(service, cipher)),),
            )
        return {
            "legacy_incidents": before[0] - after[0],
            "legacy_invitations": before[1] - after[1],
            "legacy_grants": before[2] - after[2],
        }


def _delete(connection: psycopg.Connection, table: str, now: datetime) -> int:
    allowed = {
        "incident_events",
        "api_operation_keys",
        "scene_snapshots",
        "access_invitations",
        "access_grants",
        "aed_unavailability_reports",
        "aed_assignments",
        "incidents",
    }
    if table not in allowed:
        raise ValueError("unsupported retention table")
    return connection.execute(
        f"DELETE FROM {table} WHERE expires_at <= %s", (now,)
    ).rowcount


__all__ = ["PostgresRetentionService", "RetentionResult"]
