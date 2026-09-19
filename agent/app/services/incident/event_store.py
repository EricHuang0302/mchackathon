"""Append-only incident event store.

The abstraction exposes no update or per-event delete operation. History is
append-only by construction: a correction is an additional event that
references the original, and the only removal path is
:meth:`EventStore.purge_expired`, which exists for retention.

A persistent implementation writes incident-scoped PostgreSQL rows with a
unique event ID, which gives the same create-if-absent idempotency the
in-memory store provides.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Iterable, Iterator

from .errors import INVALID_INPUT, UNAVAILABLE, ServiceError
from .models import IncidentRecord, StoredEvent


class DuplicateEventError(Exception):
    """Raised when an event ID has already been appended to an incident."""

    def __init__(self, incident_id: str, event_id: str) -> None:
        super().__init__(f"event {event_id} already appended to {incident_id}")
        self.incident_id = incident_id
        self.event_id = event_id


class EventStore(ABC):
    """Append-only event log, partitioned by incident."""

    @abstractmethod
    def append(self, event: StoredEvent) -> StoredEvent:
        """Append ``event``. Raise :class:`DuplicateEventError` if it exists."""

    @abstractmethod
    def get(self, incident_id: str, event_id: str) -> StoredEvent | None:
        """Return one event, or ``None``."""

    @abstractmethod
    def list_events(
        self,
        incident_id: str,
        *,
        after_sequence: int | None = None,
        limit: int | None = None,
    ) -> tuple[StoredEvent, ...]:
        """Return events in server receipt order.

        Receipt order is the pagination order because it is append-only and
        therefore stable. It is not the projection order: projections use
        :attr:`StoredEvent.order_key` so that server receipt time cannot
        reorder offline occurrences.
        """

    @abstractmethod
    def next_sequence(self, incident_id: str) -> int:
        """Return the sequence number the next appended event will receive."""

    @abstractmethod
    def count(self, incident_id: str) -> int:
        """Return the number of appended events for an incident."""

    @abstractmethod
    def purge_expired(self, now: datetime) -> int:
        """Delete events past ``expiresAt`` and return how many were removed.

        Retention deletion is the only removal path. Authorization must deny
        access at ``expiresAt`` rather than waiting for physical cleanup.
        """

    def contains(self, incident_id: str, event_id: str) -> bool:
        return self.get(incident_id, event_id) is not None

    def _get_by_client_sequence(
        self, incident_id: str, client_id: str, client_instance_id: str, client_sequence: int
    ) -> StoredEvent | None:
        return next(
            (event for event in self.list_events(incident_id)
             if event.envelope.client_id == client_id
             and event.envelope.client_instance_id == client_instance_id
             and event.envelope.client_sequence == client_sequence),
            None,
        )


class IncidentStore(ABC):
    """Canonical incident documents."""

    @abstractmethod
    def create(self, record: IncidentRecord) -> IncidentRecord: ...

    @abstractmethod
    def get(self, incident_id: str) -> IncidentRecord | None: ...

    @abstractmethod
    def put(self, record: IncidentRecord) -> IncidentRecord: ...

    def require(self, incident_id: str) -> IncidentRecord:
        record = self.get(incident_id)
        if record is None:
            raise ServiceError(
                INVALID_INPUT, "unknown_incident", detail={"incidentId": incident_id}
            )
        return record


class InMemoryEventStore(EventStore):
    """Deterministic in-memory event store.

    Insertion order is the server receipt order, and sequence numbers are
    assigned densely from 1 per incident, so a test can reason about receipt
    order without controlling the clock.
    """

    def __init__(self) -> None:
        self._events: dict[str, list[StoredEvent]] = {}
        self._by_id: dict[tuple[str, str], StoredEvent] = {}

    def append(self, event: StoredEvent) -> StoredEvent:
        key = (event.incident_id, event.event_id)
        if key in self._by_id:
            raise DuplicateEventError(event.incident_id, event.event_id)
        expected = self.next_sequence(event.incident_id)
        if event.server_sequence != expected:
            raise ServiceError(
                UNAVAILABLE,
                "sequence_out_of_band",
                detail={"expected": expected, "received": event.server_sequence},
            )
        self._events.setdefault(event.incident_id, []).append(event)
        self._by_id[key] = event
        return event

    def get(self, incident_id: str, event_id: str) -> StoredEvent | None:
        return self._by_id.get((incident_id, event_id))

    def list_events(
        self,
        incident_id: str,
        *,
        after_sequence: int | None = None,
        limit: int | None = None,
    ) -> tuple[StoredEvent, ...]:
        events: Iterable[StoredEvent] = self._events.get(incident_id, ())
        if after_sequence is not None:
            events = (e for e in events if e.server_sequence > after_sequence)
        if limit is not None:
            if limit < 0:
                raise ServiceError(
                    INVALID_INPUT, "negative_limit", detail={"limit": limit}
                )
            events = _take(events, limit)
        return tuple(events)

    def next_sequence(self, incident_id: str) -> int:
        return len(self._events.get(incident_id, ())) + 1

    def count(self, incident_id: str) -> int:
        return len(self._events.get(incident_id, ()))

    def purge_expired(self, now: datetime) -> int:
        removed = 0
        for incident_id, events in list(self._events.items()):
            kept = [e for e in events if e.expires_at > now]
            removed += len(events) - len(kept)
            for event in events:
                if event.expires_at <= now:
                    self._by_id.pop((incident_id, event.event_id), None)
            self._events[incident_id] = kept
        return removed

    def incident_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._events))


class InMemoryIncidentStore(IncidentStore):
    """Deterministic in-memory incident document store."""

    def __init__(self) -> None:
        self._records: dict[str, IncidentRecord] = {}

    def create(self, record: IncidentRecord) -> IncidentRecord:
        existing = self._records.get(record.incident_id)
        if existing is not None:
            # Incident registration is idempotent (section 9): re-registering
            # the same incident for the same owner returns the existing record
            # instead of resetting its revisions.
            if existing.owner_uid != record.owner_uid:
                raise ServiceError(
                    INVALID_INPUT,
                    "incident_owned_by_another_uid",
                    detail={"incidentId": record.incident_id},
                )
            if (
                existing.primary_client_id != record.primary_client_id
                or existing.rule_version != record.rule_version
            ):
                raise ServiceError(
                    INVALID_INPUT,
                    "incident_registration_mismatch",
                    detail={
                        "incidentId": record.incident_id,
                        "primaryClientId": existing.primary_client_id,
                        "ruleVersion": existing.rule_version,
                    },
                )
            return existing
        self._records[record.incident_id] = record
        return record

    def get(self, incident_id: str) -> IncidentRecord | None:
        return self._records.get(incident_id)

    def put(self, record: IncidentRecord) -> IncidentRecord:
        self._records[record.incident_id] = record
        return record

    def incident_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._records))


def _take(iterable: Iterable[StoredEvent], limit: int) -> Iterator[StoredEvent]:
    for index, item in enumerate(iterable):
        if index >= limit:
            return
        yield item


__all__ = [
    "DuplicateEventError",
    "EventStore",
    "InMemoryEventStore",
    "InMemoryIncidentStore",
    "IncidentStore",
]
