"""Shared deterministic fixtures for the synthetic scenarios.

Identifiers are derived from the scenario name and a counter, and all times
come from a fixed base instant, so two runs on two machines produce identical
output. Nothing here contacts a network, a database or a model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable

from app.services.incident import (
    FixedClock,
    IncidentEventService,
    InMemoryEventStore,
    InMemoryGrantStore,
    InMemoryIncidentStore,
    ManualClock,
    Principal,
    ROLE_PRIMARY,
    ROLE_CAPABILITIES,
    iso,
    utc,
)
from app.services.incident.ids import derive_event_id
from app.services.incident.reconciliation import ReconciliationService

#: Fixed synthetic start instant. Chosen so that scenario output never depends
#: on when the suite runs.
BASE_TIME = utc("2026-09-19T08:00:00Z")

RULE_VERSION = "demo-v1"
OWNER_UID = "synthetic-primary-uid"
PRIMARY_CLIENT_ID = "synthetic-primary-client"
PRIMARY_INSTANCE_ID = "synthetic-primary-tab"


def synthetic_incident_id(name: str) -> str:
    return derive_event_id("incident", name)


@dataclass
class EventFactory:
    """Mints deterministic event payloads for one client.

    ``client_sequence`` advances per client, and ``clientTime`` advances by the
    supplied offset, so an offline branch can be authored with occurrence times
    that deliberately interleave with another client's.
    """

    scenario: str
    client_id: str = PRIMARY_CLIENT_ID
    client_instance_id: str = PRIMARY_INSTANCE_ID
    rule_version: str = RULE_VERSION
    authority_epoch: int = 0
    state_revision: int = 0
    mode_revision: int = 0
    _counter: int = field(default=0, init=False)
    _sequence: int = field(default=0, init=False)

    def next_event_id(self, label: str) -> str:
        self._counter += 1
        return derive_event_id(self.scenario, self.client_id, label, self._counter)

    def build(
        self,
        event_type: str,
        detail: dict[str, Any],
        *,
        offset_seconds: float,
        label: str | None = None,
        source: str = "user_report",
        event_id: str | None = None,
        client_time_uncertain: bool = False,
        **overrides: Any,
    ) -> dict[str, Any]:
        self._sequence += 1
        payload: dict[str, Any] = {
            "eventId": event_id or self.next_event_id(label or event_type),
            "type": event_type,
            "detail": detail,
            "source": source,
            "clientId": self.client_id,
            "clientInstanceId": self.client_instance_id,
            "clientSequence": self._sequence,
            "clientTime": iso(BASE_TIME + timedelta(seconds=offset_seconds)),
            "clientTimeUncertain": client_time_uncertain,
            "authorityEpoch": self.authority_epoch,
            "stateRevision": self.state_revision,
            "modeRevision": self.mode_revision,
            "ruleVersion": self.rule_version,
        }
        payload.update(overrides)
        return payload

    @property
    def last_client_sequence(self) -> int:
        return self._sequence


@dataclass
class ScenarioWorld:
    """A wired, fully in-memory incident data layer."""

    name: str
    clock: ManualClock
    events: InMemoryEventStore
    incidents: InMemoryIncidentStore
    grants: InMemoryGrantStore
    ingestion: IncidentEventService
    reconciliation: ReconciliationService
    incident_id: str

    def primary(self) -> Principal:
        return Principal(
            uid=OWNER_UID,
            role=ROLE_PRIMARY,
            incident_id=self.incident_id,
            client_id=PRIMARY_CLIENT_ID,
            client_instance_id=PRIMARY_INSTANCE_ID,
            capabilities=ROLE_CAPABILITIES[ROLE_PRIMARY],
        )

    def helper(self, uid: str, role: str, helper_id: str) -> Principal:
        return Principal(
            uid=uid,
            role=role,
            incident_id=self.incident_id,
            helper_id=helper_id,
            capabilities=ROLE_CAPABILITIES[role],
        )

    def all_events(self) -> tuple[Any, ...]:
        return self.events.list_events(self.incident_id)

    def now(self) -> datetime:
        return self.clock.now()


def build_world(name: str, *, start: datetime | None = None) -> ScenarioWorld:
    """Wire an incident data layer for one scenario and register the incident."""
    clock = ManualClock(start or BASE_TIME)
    events = InMemoryEventStore()
    incidents = InMemoryIncidentStore()
    grants = InMemoryGrantStore()
    ingestion = IncidentEventService(events, incidents, clock)
    reconciliation = ReconciliationService(ingestion, events, clock)
    incident_id = synthetic_incident_id(name)
    ingestion.register_incident(
        incident_id=incident_id,
        owner_uid=OWNER_UID,
        primary_client_id=PRIMARY_CLIENT_ID,
        rule_version=RULE_VERSION,
    )
    return ScenarioWorld(
        name=name,
        clock=clock,
        events=events,
        incidents=incidents,
        grants=grants,
        ingestion=ingestion,
        reconciliation=reconciliation,
        incident_id=incident_id,
    )


def conflict_summary(conflicts: Iterable[Any]) -> list[dict[str, Any]]:
    return [
        {"eventId": c.event_id, "code": c.code, "reason": c.reason} for c in conflicts
    ]


def ack_summary(acks: Iterable[Any]) -> list[dict[str, Any]]:
    return [
        {"eventId": a.event_id, "status": a.status, "clientSequence": a.client_sequence}
        for a in acks
    ]


__all__ = [
    "BASE_TIME",
    "EventFactory",
    "FixedClock",
    "OWNER_UID",
    "PRIMARY_CLIENT_ID",
    "PRIMARY_INSTANCE_ID",
    "RULE_VERSION",
    "ScenarioWorld",
    "ack_summary",
    "build_world",
    "conflict_summary",
    "synthetic_incident_id",
]
