"""Authorized read models built from the canonical incident event stream."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from .access import (
    GrantStore,
    READ_MIST,
    READ_SCENE_SNAPSHOT,
    READ_TIMELINE,
    Principal,
    resolve_principal,
)
from .clock import Clock
from .errors import EXPIRED, INVALID_INPUT, RetentionPolicy, ServiceError
from .event_store import EventStore, IncidentStore
from .handoff import DEFAULT_PAGE_SIZE, build_handoff_timeline, project_mist
from .models import IncidentRecord, MistReport, SceneSnapshot, StoredEvent, TimelinePage
from .scene_snapshot import FreshnessPolicy, project_scene_snapshot


@dataclass(frozen=True, slots=True)
class HandoffReadModel:
    """Snapshot-first EMS view derived from one immutable event boundary."""

    snapshot: SceneSnapshot
    mist: MistReport
    timeline: TimelinePage

    def to_dict(self) -> dict:
        return {
            "snapshot": self.snapshot.to_dict(),
            "mist": self.mist.to_dict(),
            "timeline": self.timeline.to_dict(),
        }


class IncidentReadModelService:
    """Resolve incident access before projecting shared read models.

    Authentication stays with workstream 1. This service accepts the verified
    user identifier, resolves its incident-scoped role, and applies the same
    event boundary to the scene snapshot and MIST projection.
    """

    def __init__(
        self,
        incidents: IncidentStore,
        events: EventStore,
        grants: GrantStore,
        clock: Clock,
        *,
        freshness: FreshnessPolicy | None = None,
        retention: RetentionPolicy | None = None,
    ) -> None:
        self._incidents = incidents
        self._events = events
        self._grants = grants
        self._clock = clock
        self._freshness = freshness or FreshnessPolicy()
        self._retention = retention or RetentionPolicy()

    def scene_snapshot(self, *, incident_id: str, uid: str) -> SceneSnapshot:
        incident, principal, now = self._authorize(incident_id=incident_id, uid=uid)
        principal.require(READ_SCENE_SNAPSHOT)
        return self._snapshot(incident, now=now)

    def mist(self, *, incident_id: str, uid: str) -> MistReport:
        incident, principal, now = self._authorize(incident_id=incident_id, uid=uid)
        principal.require(READ_MIST)
        events = self._retained_events(incident_id, now=now)
        snapshot = self._snapshot(incident, events=events, now=now)
        return project_mist(
            incident,
            events,
            now=now,
            viewer_role=principal.role,
            policy=self._freshness,
            snapshot=snapshot,
            through_sequence=snapshot.generated_through_sequence,
        )

    def timeline(
        self,
        *,
        incident_id: str,
        uid: str,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> TimelinePage:
        _, principal, now = self._authorize(incident_id=incident_id, uid=uid)
        principal.require(READ_TIMELINE)
        return self._timeline_page(
            incident_id=incident_id,
            principal=principal,
            now=now,
            cursor=cursor,
            page_size=page_size,
        )

    def handoff(
        self,
        *,
        incident_id: str,
        uid: str,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> HandoffReadModel:
        incident, principal, now = self._authorize(incident_id=incident_id, uid=uid)
        principal.require(READ_SCENE_SNAPSHOT)
        principal.require(READ_MIST)
        principal.require(READ_TIMELINE)
        boundary, inner_cursor = _decode_window_cursor(cursor)
        events = self._retained_events(incident_id, now=now, through_sequence=boundary)
        if boundary is None:
            boundary = events[-1].server_sequence if events else 0
        snapshot = self._snapshot(incident, events=events, now=now)
        mist = project_mist(
            incident,
            events,
            now=now,
            viewer_role=principal.role,
            policy=self._freshness,
            snapshot=snapshot,
            through_sequence=snapshot.generated_through_sequence,
        )
        timeline = self._build_timeline_page(
            events,
            principal=principal,
            boundary=boundary,
            inner_cursor=inner_cursor,
            page_size=page_size,
        )
        return HandoffReadModel(snapshot=snapshot, mist=mist, timeline=timeline)

    def _authorize(
        self, *, incident_id: str, uid: str
    ) -> tuple[IncidentRecord, Principal, datetime]:
        incident = self._incidents.require(incident_id)
        now = self._clock.now()
        if now >= incident.expires_at:
            raise ServiceError(EXPIRED, "incident_expired", detail={"incidentId": incident_id})
        principal = resolve_principal(
            incident_id=incident_id,
            owner_uid=incident.owner_uid,
            uid=uid,
            now=now,
            grants=self._grants,
        )
        return incident, principal, now

    def _retained_events(
        self,
        incident_id: str,
        *,
        now: datetime,
        through_sequence: int | None = None,
    ) -> tuple[StoredEvent, ...]:
        return tuple(
            event
            for event in self._events.list_events(incident_id)
            if event.expires_at > now
            and (through_sequence is None or event.server_sequence <= through_sequence)
        )

    def _snapshot(
        self,
        incident: IncidentRecord,
        *,
        now: datetime,
        events: tuple[StoredEvent, ...] | None = None,
    ) -> SceneSnapshot:
        materialised = (
            events
            if events is not None
            else self._retained_events(incident.incident_id, now=now)
        )
        boundary = materialised[-1].server_sequence if materialised else 0
        return project_scene_snapshot(
            incident,
            materialised,
            now=now,
            policy=self._freshness,
            retention=self._retention,
            through_sequence=boundary,
        )

    def _timeline_page(
        self,
        *,
        incident_id: str,
        principal: Principal,
        now: datetime,
        cursor: str | None,
        page_size: int,
    ) -> TimelinePage:
        boundary, inner_cursor = _decode_window_cursor(cursor)
        events = self._retained_events(
            incident_id,
            now=now,
            through_sequence=boundary,
        )
        if boundary is None:
            boundary = events[-1].server_sequence if events else 0
        return self._build_timeline_page(
            events,
            principal=principal,
            boundary=boundary,
            inner_cursor=inner_cursor,
            page_size=page_size,
        )

    @staticmethod
    def _build_timeline_page(
        events: tuple[StoredEvent, ...],
        *,
        principal: Principal,
        boundary: int,
        inner_cursor: str | None,
        page_size: int,
    ) -> TimelinePage:
        page = build_handoff_timeline(
            events,
            viewer_role=principal.role,
            cursor=inner_cursor,
            page_size=page_size,
        )
        next_cursor = (
            _encode_window_cursor(boundary, page.next_cursor)
            if page.next_cursor is not None
            else None
        )
        return replace(page, next_cursor=next_cursor)


_WINDOW_CURSOR_PREFIX = "window:"
_MAX_CURSOR_NUMBER_DIGITS = 19


def _decode_window_cursor(cursor: str | None) -> tuple[int | None, str | None]:
    if cursor is None:
        return None, None
    if not isinstance(cursor, str) or not cursor.startswith(_WINDOW_CURSOR_PREFIX):
        raise ServiceError(INVALID_INPUT, "malformed_cursor", detail={"cursor": cursor})
    parts = cursor.split(":")
    if len(parts) != 3:
        raise ServiceError(INVALID_INPUT, "malformed_cursor", detail={"cursor": cursor})
    through_raw, after_raw = parts[1:]
    if (
        not through_raw.isascii()
        or not through_raw.isdigit()
        or not after_raw.isascii()
        or not after_raw.isdigit()
        or len(through_raw) > _MAX_CURSOR_NUMBER_DIGITS
        or len(after_raw) > _MAX_CURSOR_NUMBER_DIGITS
    ):
        raise ServiceError(INVALID_INPUT, "malformed_cursor", detail={"cursor": cursor})
    through = int(through_raw)
    after = int(after_raw)
    if after > through:
        raise ServiceError(INVALID_INPUT, "malformed_cursor", detail={"cursor": cursor})
    return through, f"seq:{after}"


def _encode_window_cursor(boundary: int, inner_cursor: str) -> str:
    after_raw = inner_cursor.removeprefix("seq:")
    return f"{_WINDOW_CURSOR_PREFIX}{boundary}:{after_raw}"


__all__ = ["HandoffReadModel", "IncidentReadModelService"]
