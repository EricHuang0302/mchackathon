from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Protocol
from uuid import uuid4

import psycopg

from app.api.errors import ApiError, unavailable
from app.schemas.contracts import SessionResponse


class TokenVerifier(Protocol):
    def verify(self, token: str) -> str: ...


class LocalSessionStore:
    """Opaque, expiring local sessions; only token hashes are persisted."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        with psycopg.connect(dsn) as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS local_sessions (
                token_hash text PRIMARY KEY, actor_id uuid NOT NULL,
                expires_at timestamptz NOT NULL, revoked_at timestamptz
            )""")

    def create(self) -> SessionResponse:
        token = secrets.token_urlsafe(48)
        actor_id = uuid4()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=12)
        try:
            with psycopg.connect(self.dsn) as connection:
                connection.execute("DELETE FROM local_sessions WHERE expires_at <= now() OR revoked_at IS NOT NULL")
                connection.execute(
                    "INSERT INTO local_sessions (token_hash, actor_id, expires_at) VALUES (%s, %s, %s)",
                    (sha256(token.encode()).hexdigest(), actor_id, expires_at),
                )
        except psycopg.Error:
            raise unavailable() from None
        return SessionResponse(actorId=actor_id, sessionToken=token, expiresAt=expires_at)

    def verify(self, token: str) -> str:
        if len(token) > 256:
            raise ApiError("unauthorized", 401, "Invalid authentication")
        try:
            with psycopg.connect(self.dsn) as connection:
                row = connection.execute(
                    "SELECT actor_id FROM local_sessions WHERE token_hash = %s AND expires_at > now() AND revoked_at IS NULL",
                    (sha256(token.encode()).hexdigest(),),
                ).fetchone()
        except psycopg.Error:
            raise unavailable() from None
        if not row:
            raise ApiError("unauthorized", 401, "Invalid authentication")
        return str(row[0])


class UnavailableTokenVerifier:
    def verify(self, token: str) -> str:
        raise unavailable()


def bearer_token(header: str | None) -> str:
    if not header or not header.startswith("Bearer ") or not header[7:]:
        raise ApiError("unauthorized", 401, "Bearer token required")
    return header[7:]
