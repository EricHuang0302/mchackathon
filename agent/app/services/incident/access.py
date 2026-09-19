"""Incident-scoped access grants and the role capability matrix.

This module decides what an already-authenticated principal may do with one
incident. It does not issue, sign or verify tokens: identity arrives from the
caller (workstream 1) and only the incident scope is resolved here.

The matrix below is enforced inside the backend before PostgreSQL reads or
writes. Database credentials never establish the caller's incident scope.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Iterable

from .errors import EXPIRED, INVALID_INPUT, UNAUTHORIZED, ServiceError

ROLE_PRIMARY: Final = "primary"
ROLE_AED_RUNNER: Final = "aed_runner"
ROLE_AMBULANCE_GREETER: Final = "ambulance_greeter"
ROLE_EMS_VIEWER: Final = "ems_viewer"

ROLES: Final = (ROLE_PRIMARY, ROLE_AED_RUNNER, ROLE_AMBULANCE_GREETER, ROLE_EMS_VIEWER)
ROLE_SET: Final = frozenset(ROLES)

#: Helper roles own a ``helpers/{helperId}`` task document.
HELPER_ROLES: Final = frozenset({ROLE_AED_RUNNER, ROLE_AMBULANCE_GREETER})

# Capabilities. Kept as plain strings so the same names can appear in the
# PostgreSQL integration tests and in the documentation table.
READ_INCIDENT: Final = "read:incident"
READ_SCENE_SNAPSHOT: Final = "read:sceneSnapshot"
READ_MIST: Final = "read:mist"
READ_TIMELINE: Final = "read:timeline"
READ_OWN_HELPER_VIEW: Final = "read:ownHelperView"
READ_ALL_HELPERS: Final = "read:allHelpers"
WRITE_INCIDENT_EVENTS: Final = "write:incidentEvents"
WRITE_OWN_HELPER_UPDATES: Final = "write:ownHelperUpdates"
MANAGE_SHARES: Final = "manage:shares"

#: What each role may do.
#:
#: An AED runner gets retrieval information only: no snapshot, no MIST, no
#: timeline. An ambulance greeter reads the shared scene snapshot but not the
#: full clinical timeline. An EMS viewer reads and never writes.
ROLE_CAPABILITIES: Final[dict[str, frozenset[str]]] = {
    ROLE_PRIMARY: frozenset(
        {
            READ_INCIDENT,
            READ_SCENE_SNAPSHOT,
            READ_MIST,
            READ_TIMELINE,
            READ_ALL_HELPERS,
            READ_OWN_HELPER_VIEW,
            WRITE_INCIDENT_EVENTS,
            MANAGE_SHARES,
        }
    ),
    ROLE_AED_RUNNER: frozenset({READ_OWN_HELPER_VIEW, WRITE_OWN_HELPER_UPDATES}),
    ROLE_AMBULANCE_GREETER: frozenset(
        {READ_OWN_HELPER_VIEW, READ_SCENE_SNAPSHOT, WRITE_OWN_HELPER_UPDATES}
    ),
    ROLE_EMS_VIEWER: frozenset({READ_SCENE_SNAPSHOT, READ_MIST, READ_TIMELINE}),
}


@dataclass(frozen=True, slots=True)
class AccessGrant:
    """An incident-scoped, expiring grant created from a share invitation.

    ``expires_at`` governs authorization immediately. Revocation stops future
    access but cannot retract what a viewer already saw.
    """

    grant_id: str
    incident_id: str
    uid: str
    scope: str
    expires_at: datetime
    helper_id: str | None = None
    revoked_at: datetime | None = None

    def is_valid_at(self, now: datetime) -> bool:
        if self.revoked_at is not None and self.revoked_at <= now:
            return False
        return now < self.expires_at


@dataclass(frozen=True, slots=True)
class Principal:
    """An authenticated caller resolved against one incident."""

    uid: str
    role: str
    incident_id: str
    client_id: str | None = None
    client_instance_id: str | None = None
    helper_id: str | None = None
    grant_id: str | None = None
    capabilities: frozenset[str] = field(default_factory=frozenset)

    @property
    def actor_id(self) -> str:
        return self.uid

    def can(self, capability: str) -> bool:
        return capability in self.capabilities

    def require(self, capability: str) -> None:
        if not self.can(capability):
            raise ServiceError(
                UNAUTHORIZED,
                "capability_denied",
                detail={
                    "role": self.role,
                    "capability": capability,
                    "incidentId": self.incident_id,
                },
            )


class GrantStore(ABC):
    """Lookup for incident-scoped grants.

    A persistent implementation resolves an authenticated uid against an
    incident-scoped PostgreSQL grant row.
    """

    @abstractmethod
    def get(self, incident_id: str, uid: str) -> AccessGrant | None: ...

    @abstractmethod
    def put(self, grant: AccessGrant) -> AccessGrant: ...

    @abstractmethod
    def revoke(self, incident_id: str, uid: str, at: datetime) -> AccessGrant | None: ...


class InMemoryGrantStore(GrantStore):
    """Deterministic in-memory grant store for tests and scenarios."""

    def __init__(self, grants: Iterable[AccessGrant] = ()) -> None:
        self._grants: dict[tuple[str, str], AccessGrant] = {}
        for grant in grants:
            self.put(grant)

    def get(self, incident_id: str, uid: str) -> AccessGrant | None:
        return self._grants.get((incident_id, uid))

    def put(self, grant: AccessGrant) -> AccessGrant:
        if grant.scope not in ROLE_SET:
            raise ServiceError(
                INVALID_INPUT, "unknown_scope", detail={"scope": grant.scope}
            )
        if grant.scope in HELPER_ROLES and not grant.helper_id:
            raise ServiceError(
                INVALID_INPUT, "helper_grant_requires_helper_id",
                detail={"scope": grant.scope},
            )
        self._grants[(grant.incident_id, grant.uid)] = grant
        return grant

    def revoke(self, incident_id: str, uid: str, at: datetime) -> AccessGrant | None:
        existing = self._grants.get((incident_id, uid))
        if existing is None:
            return None
        revoked = AccessGrant(
            grant_id=existing.grant_id,
            incident_id=existing.incident_id,
            uid=existing.uid,
            scope=existing.scope,
            expires_at=existing.expires_at,
            helper_id=existing.helper_id,
            revoked_at=at,
        )
        self._grants[(incident_id, uid)] = revoked
        return revoked


def resolve_principal(
    *,
    incident_id: str,
    owner_uid: str,
    uid: str,
    now: datetime,
    grants: GrantStore | None = None,
    client_id: str | None = None,
    client_instance_id: str | None = None,
) -> Principal:
    """Resolve ``uid`` against one incident, or raise.

    Ownership is checked first so that the primary session never depends on a
    share grant. Anyone else needs an unexpired, unrevoked grant scoped to this
    incident; a grant for another incident is not a grant for this one.
    """
    if uid == owner_uid:
        return Principal(
            uid=uid,
            role=ROLE_PRIMARY,
            incident_id=incident_id,
            client_id=client_id,
            client_instance_id=client_instance_id,
            capabilities=ROLE_CAPABILITIES[ROLE_PRIMARY],
        )

    grant = grants.get(incident_id, uid) if grants is not None else None
    if grant is None:
        raise ServiceError(
            UNAUTHORIZED, "no_grant_for_incident", detail={"incidentId": incident_id}
        )
    if grant.incident_id != incident_id:
        raise ServiceError(
            UNAUTHORIZED, "grant_scope_mismatch", detail={"incidentId": incident_id}
        )
    if not grant.is_valid_at(now):
        reason = "grant_revoked" if grant.revoked_at is not None else "grant_expired"
        raise ServiceError(EXPIRED, reason, detail={"incidentId": incident_id})

    return Principal(
        uid=uid,
        role=grant.scope,
        incident_id=incident_id,
        client_id=client_id,
        client_instance_id=client_instance_id,
        helper_id=grant.helper_id,
        grant_id=grant.grant_id,
        capabilities=ROLE_CAPABILITIES[grant.scope],
    )


__all__ = [
    "AccessGrant",
    "GrantStore",
    "HELPER_ROLES",
    "InMemoryGrantStore",
    "MANAGE_SHARES",
    "Principal",
    "READ_ALL_HELPERS",
    "READ_INCIDENT",
    "READ_MIST",
    "READ_OWN_HELPER_VIEW",
    "READ_SCENE_SNAPSHOT",
    "READ_TIMELINE",
    "ROLES",
    "ROLE_AED_RUNNER",
    "ROLE_AMBULANCE_GREETER",
    "ROLE_CAPABILITIES",
    "ROLE_EMS_VIEWER",
    "ROLE_PRIMARY",
    "WRITE_INCIDENT_EVENTS",
    "WRITE_OWN_HELPER_UPDATES",
    "resolve_principal",
]
