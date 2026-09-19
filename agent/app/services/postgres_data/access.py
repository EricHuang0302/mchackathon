"""PostgreSQL persistence for incident invitations and access grants."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg

from .connection import ConnectionBoundRepository

from app.services.incident.access import (
    HELPER_ROLES,
    ROLE_SET,
    AccessGrant,
    GrantStore,
)
from app.services.incident.errors import INVALID_INPUT, UNAVAILABLE, ServiceError


@dataclass(frozen=True, slots=True)
class AccessInvitation:
    """Hashed, expiring invitation metadata; raw secrets are never persisted."""

    invitation_id: str
    incident_id: str
    secret_hash: str
    encrypted_secret: bytes
    scope: str
    idempotency_key: str
    created_at: datetime
    expires_at: datetime
    helper_id: str | None = None
    redeemed_at: datetime | None = None
    redeemed_by_uid: str | None = None
    revoked_at: datetime | None = None

    def is_valid_at(self, now: datetime) -> bool:
        return (
            self.redeemed_at is None
            and self.revoked_at is None
            and now < self.expires_at
        )


def _validate_scope(scope: str, helper_id: str | None) -> None:
    if scope not in ROLE_SET or scope == "primary":
        raise ServiceError(INVALID_INPUT, "unknown_scope", detail={"scope": scope})
    if scope in HELPER_ROLES and not helper_id:
        raise ServiceError(
            INVALID_INPUT,
            "helper_grant_requires_helper_id",
            detail={"scope": scope},
        )


class PostgresInvitationStore(ConnectionBoundRepository):
    """Invitation lookup and one-time redemption with row-level locking."""

    def put(self, invitation: AccessInvitation) -> AccessInvitation:
        _validate_scope(invitation.scope, invitation.helper_id)
        if len(invitation.secret_hash) != 64:
            raise ServiceError(INVALID_INPUT, "invalid_secret_hash")
        try:
            with self._connection_scope() as connection:
                connection.execute(
                    """
                    INSERT INTO access_invitations (
                        invitation_id, incident_id, secret_hash, encrypted_secret,
                        scope, helper_id,
                        idempotency_key, created_at, expires_at, redeemed_at,
                        redeemed_by_uid, revoked_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (incident_id, idempotency_key) DO NOTHING
                    """,
                    (
                        invitation.invitation_id,
                        invitation.incident_id,
                        invitation.secret_hash,
                        invitation.encrypted_secret,
                        invitation.scope,
                        invitation.helper_id,
                        invitation.idempotency_key,
                        invitation.created_at,
                        invitation.expires_at,
                        invitation.redeemed_at,
                        invitation.redeemed_by_uid,
                        invitation.revoked_at,
                    ),
                )
                row = connection.execute(
                    f"SELECT {_INVITATION_COLUMNS} FROM access_invitations WHERE incident_id = %s AND idempotency_key = %s",
                    (invitation.incident_id, invitation.idempotency_key),
                ).fetchone()
        except psycopg.Error as exc:
            raise ServiceError(
                UNAVAILABLE, "postgres_unavailable", detail={"type": type(exc).__name__}
            ) from None
        stored = _invitation_from_row(row)
        if (
            stored.scope != invitation.scope
            or stored.helper_id != invitation.helper_id
            or (stored.expires_at - stored.created_at)
            != (invitation.expires_at - invitation.created_at)
        ):
            raise ServiceError(
                INVALID_INPUT,
                "idempotency_key_reused_for_different_content",
                detail={"incidentId": invitation.incident_id},
            )
        return stored

    def get_by_secret_hash(self, secret_hash: str) -> AccessInvitation | None:
        return self._get("secret_hash", secret_hash)

    def get_by_idempotency_key(
        self, incident_id: str, idempotency_key: str
    ) -> AccessInvitation | None:
        try:
            with self._connection_scope() as connection:
                row = connection.execute(
                    f"SELECT {_INVITATION_COLUMNS} FROM access_invitations WHERE incident_id = %s AND idempotency_key = %s",
                    (incident_id, idempotency_key),
                ).fetchone()
        except psycopg.Error as exc:
            raise ServiceError(
                UNAVAILABLE, "postgres_unavailable", detail={"type": type(exc).__name__}
            ) from None
        return _invitation_from_row(row) if row else None

    def redeem(
        self, secret_hash: str, uid: str, at: datetime
    ) -> AccessInvitation | None:
        try:
            with self._connection_scope() as connection:
                row = connection.execute(
                    f"""
                    UPDATE access_invitations
                    SET redeemed_at = %s, redeemed_by_uid = %s
                    WHERE secret_hash = %s
                        AND redeemed_at IS NULL
                        AND revoked_at IS NULL
                        AND expires_at > %s
                    RETURNING {_INVITATION_COLUMNS}
                    """,
                    (at, uid, secret_hash, at),
                ).fetchone()
        except psycopg.Error as exc:
            raise ServiceError(
                UNAVAILABLE, "postgres_unavailable", detail={"type": type(exc).__name__}
            ) from None
        return _invitation_from_row(row) if row else None

    def revoke_incident(self, incident_id: str, at: datetime) -> int:
        try:
            with self._connection_scope() as connection:
                cursor = connection.execute(
                    """
                    UPDATE access_invitations SET revoked_at = %s
                    WHERE incident_id = %s AND revoked_at IS NULL AND redeemed_at IS NULL
                    """,
                    (at, incident_id),
                )
                return cursor.rowcount
        except psycopg.Error as exc:
            raise ServiceError(
                UNAVAILABLE, "postgres_unavailable", detail={"type": type(exc).__name__}
            ) from None

    def _get(self, column: str, value: str) -> AccessInvitation | None:
        if column != "secret_hash":
            raise ValueError("unsupported invitation lookup")
        try:
            with self._connection_scope() as connection:
                row = connection.execute(
                    f"SELECT {_INVITATION_COLUMNS} FROM access_invitations WHERE {column} = %s",
                    (value,),
                ).fetchone()
        except psycopg.Error as exc:
            raise ServiceError(
                UNAVAILABLE, "postgres_unavailable", detail={"type": type(exc).__name__}
            ) from None
        return _invitation_from_row(row) if row else None


class PostgresGrantStore(ConnectionBoundRepository, GrantStore):
    """Incident-scoped access grants backed by normalized rows."""

    def get(self, incident_id: str, uid: str) -> AccessGrant | None:
        try:
            with self._connection_scope() as connection:
                row = connection.execute(
                    f"SELECT {_GRANT_COLUMNS} FROM access_grants WHERE incident_id = %s AND uid = %s",
                    (incident_id, uid),
                ).fetchone()
        except psycopg.Error as exc:
            raise ServiceError(
                UNAVAILABLE, "postgres_unavailable", detail={"type": type(exc).__name__}
            ) from None
        return _grant_from_row(row) if row else None

    def put(self, grant: AccessGrant) -> AccessGrant:
        _validate_scope(grant.scope, grant.helper_id)
        try:
            with self._connection_scope() as connection:
                row = connection.execute(
                    f"""
                    INSERT INTO access_grants (
                        grant_id, incident_id, uid, scope, helper_id, expires_at, revoked_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (incident_id, uid) DO UPDATE SET
                        grant_id = EXCLUDED.grant_id,
                        scope = EXCLUDED.scope,
                        helper_id = EXCLUDED.helper_id,
                        expires_at = EXCLUDED.expires_at,
                        revoked_at = EXCLUDED.revoked_at
                    RETURNING {_GRANT_COLUMNS}
                    """,
                    (
                        grant.grant_id,
                        grant.incident_id,
                        grant.uid,
                        grant.scope,
                        grant.helper_id,
                        grant.expires_at,
                        grant.revoked_at,
                    ),
                ).fetchone()
        except psycopg.Error as exc:
            raise ServiceError(
                UNAVAILABLE, "postgres_unavailable", detail={"type": type(exc).__name__}
            ) from None
        return _grant_from_row(row)

    def revoke(self, incident_id: str, uid: str, at: datetime) -> AccessGrant | None:
        try:
            with self._connection_scope() as connection:
                row = connection.execute(
                    f"""
                    UPDATE access_grants SET revoked_at = %s
                    WHERE incident_id = %s AND uid = %s
                    RETURNING {_GRANT_COLUMNS}
                    """,
                    (at, incident_id, uid),
                ).fetchone()
        except psycopg.Error as exc:
            raise ServiceError(
                UNAVAILABLE, "postgres_unavailable", detail={"type": type(exc).__name__}
            ) from None
        return _grant_from_row(row) if row else None

    def revoke_incident(self, incident_id: str, at: datetime) -> int:
        try:
            with self._connection_scope() as connection:
                cursor = connection.execute(
                    "UPDATE access_grants SET revoked_at = %s WHERE incident_id = %s AND revoked_at IS NULL",
                    (at, incident_id),
                )
                return cursor.rowcount
        except psycopg.Error as exc:
            raise ServiceError(
                UNAVAILABLE, "postgres_unavailable", detail={"type": type(exc).__name__}
            ) from None


_INVITATION_COLUMNS = """
invitation_id, incident_id, secret_hash, encrypted_secret, scope,
idempotency_key, created_at, expires_at, helper_id, redeemed_at,
redeemed_by_uid, revoked_at
"""


def _invitation_from_row(row: tuple) -> AccessInvitation:
    return AccessInvitation(
        invitation_id=row[0],
        incident_id=row[1],
        secret_hash=row[2],
        encrypted_secret=bytes(row[3]),
        scope=row[4],
        idempotency_key=row[5],
        created_at=row[6],
        expires_at=row[7],
        helper_id=row[8],
        redeemed_at=row[9],
        redeemed_by_uid=row[10],
        revoked_at=row[11],
    )


_GRANT_COLUMNS = "grant_id, incident_id, uid, scope, expires_at, helper_id, revoked_at"


def _grant_from_row(row: tuple) -> AccessGrant:
    return AccessGrant(
        grant_id=row[0],
        incident_id=row[1],
        uid=row[2],
        scope=row[3],
        expires_at=row[4],
        helper_id=row[5],
        revoked_at=row[6],
    )


__all__ = ["AccessInvitation", "PostgresGrantStore", "PostgresInvitationStore"]
