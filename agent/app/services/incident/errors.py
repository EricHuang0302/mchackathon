"""Error codes shared by the incident data services.

The codes reproduce the API error vocabulary in ``docs/sdd.md`` section 9 so
that workstream 1 can map them onto HTTP responses without translation:
``unauthorized``, ``expired``, ``stale_revision``, ``rule_mismatch``,
``unavailable`` and ``invalid_input``.

``reason`` carries a stable machine-readable detail for diagnostics and tests.
It is never a user-facing message.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

UNAUTHORIZED: Final = "unauthorized"
EXPIRED: Final = "expired"
STALE_REVISION: Final = "stale_revision"
RULE_MISMATCH: Final = "rule_mismatch"
UNAVAILABLE: Final = "unavailable"
INVALID_INPUT: Final = "invalid_input"

ERROR_CODES: Final = frozenset(
    {UNAUTHORIZED, EXPIRED, STALE_REVISION, RULE_MISMATCH, UNAVAILABLE, INVALID_INPUT}
)


class ServiceError(Exception):
    """A request-level failure that aborts the whole operation.

    Per-event failures inside a batch are reported as
    :class:`~app.services.incident.models.EventConflict` entries instead, so that a
    single bad event does not discard an otherwise valid offline batch.
    """

    def __init__(self, code: str, reason: str, *, detail: dict | None = None) -> None:
        if code not in ERROR_CODES:
            raise ValueError(f"unknown error code: {code}")
        super().__init__(f"{code}: {reason}")
        self.code = code
        self.reason = reason
        self.detail = dict(detail or {})

    def as_dict(self) -> dict:
        return {"code": self.code, "reason": self.reason, "detail": dict(self.detail)}


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """Retention window applied to incident-scoped documents.

    Expiry governs authorization immediately; physical deletion is
    asynchronous, so callers must deny access at ``expiresAt`` rather than
    waiting for a purge to run.
    """

    incident_seconds: int = 24 * 60 * 60
    event_seconds: int = 24 * 60 * 60
    projection_seconds: int = 24 * 60 * 60
    grant_seconds: int = 4 * 60 * 60
    invite_seconds: int = 30 * 60
