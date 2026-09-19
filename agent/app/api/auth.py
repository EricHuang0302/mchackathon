from __future__ import annotations

from typing import Protocol

import firebase_admin
from firebase_admin import auth

from app.api.errors import ApiError


class TokenVerifier(Protocol):
    def verify(self, token: str) -> str: ...


class FirebaseTokenVerifier:
    def __init__(self):
        try:
            firebase_admin.get_app()
        except ValueError:
            firebase_admin.initialize_app()

    def verify(self, token: str) -> str:
        try:
            claims = auth.verify_id_token(token, check_revoked=True)
        except Exception:
            raise ApiError("unauthorized", 401, "Invalid authentication") from None
        uid = claims.get("uid")
        if not isinstance(uid, str) or not uid:
            raise ApiError("unauthorized", 401, "Invalid authentication")
        return uid


def bearer_token(header: str | None) -> str:
    if not header or not header.startswith("Bearer ") or not header[7:]:
        raise ApiError("unauthorized", 401, "Bearer token required")
    return header[7:]
