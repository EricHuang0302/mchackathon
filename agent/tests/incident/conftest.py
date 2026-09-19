"""Shared fixtures for the incident data-layer tests.

Everything is synthetic and deterministic: a manual clock, in-memory stores and
derived identifiers. No test contacts a network, a database or a model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest

from app.services.incident import (
    IncidentEventService,
    InMemoryEventStore,
    InMemoryGrantStore,
    InMemoryIncidentStore,
    ManualClock,
    Principal,
    ROLE_CAPABILITIES,
    ROLE_PRIMARY,
    iso,
    utc,
)
from app.services.incident.ids import derive_event_id
from app.services.incident.reconciliation import ReconciliationService

BASE_TIME = utc("2026-09-19T08:00:00Z")
RULE_VERSION = "demo-v1"
OWNER_UID = "test-primary-uid"
PRIMARY_CLIENT_ID = "test-primary-client"
PRIMARY_INSTANCE_ID = "test-primary-tab"
INCIDENT_ID = derive_event_id("test", "incident")


@dataclass
class Factory:
    """Mints deterministic event payloads for one client."""

    namespace: str = "test"
    client_id: str = PRIMARY_CLIENT_ID
    client_instance_id: str = PRIMARY_INSTANCE_ID
    rule_version: str = RULE_VERSION
    authority_epoch: int = 0
    state_revision: int = 0
    mode_revision: int = 0
    _counter: int = field(default=0, init=False)
    _sequence: int = field(default=0, init=False)

    def build(
        self,
        event_type: str,
        detail: dict[str, Any] | None = None,
        *,
        at: float = 0.0,
        source: str = "user_report",
        event_id: str | None = None,
        **overrides: Any,
    ) -> dict[str, Any]:
        self._counter += 1
        self._sequence += 1
        payload: dict[str, Any] = {
            "eventId": event_id
            or derive_event_id(self.namespace, self.client_id, self._counter),
            "type": event_type,
            "detail": dict(detail or {}),
            "source": source,
            "clientId": self.client_id,
            "clientInstanceId": self.client_instance_id,
            "clientSequence": self._sequence,
            "clientTime": iso(BASE_TIME + timedelta(seconds=at)),
            "authorityEpoch": self.authority_epoch,
            "stateRevision": self.state_revision,
            "modeRevision": self.mode_revision,
            "ruleVersion": self.rule_version,
        }
        payload.update(overrides)
        return payload

    @property
    def client_sequence(self) -> int:
        return self._sequence


@dataclass
class World:
    clock: ManualClock
    events: InMemoryEventStore
    incidents: InMemoryIncidentStore
    grants: InMemoryGrantStore
    ingestion: IncidentEventService
    reconciliation: ReconciliationService
    incident_id: str

    def ingest(self, payloads: list[Any], principal: Principal | None = None) -> Any:
        return self.ingestion.ingest_batch(
            self.incident_id, payloads, principal=principal or self.primary
        )

    @property
    def primary(self) -> Principal:
        return Principal(
            uid=OWNER_UID,
            role=ROLE_PRIMARY,
            incident_id=self.incident_id,
            client_id=PRIMARY_CLIENT_ID,
            client_instance_id=PRIMARY_INSTANCE_ID,
            capabilities=ROLE_CAPABILITIES[ROLE_PRIMARY],
        )

    def principal_for(self, uid: str, role: str, helper_id: str | None = None) -> Principal:
        return Principal(
            uid=uid,
            role=role,
            incident_id=self.incident_id,
            helper_id=helper_id,
            capabilities=ROLE_CAPABILITIES[role],
        )

    @property
    def incident(self) -> Any:
        return self.ingestion.get_incident(self.incident_id)

    @property
    def all_events(self) -> tuple[Any, ...]:
        return self.events.list_events(self.incident_id)

    def now(self) -> Any:
        return self.clock.now()


def make_world(incident_id: str = INCIDENT_ID) -> World:
    clock = ManualClock(BASE_TIME)
    events = InMemoryEventStore()
    incidents = InMemoryIncidentStore()
    grants = InMemoryGrantStore()
    ingestion = IncidentEventService(events, incidents, clock)
    reconciliation = ReconciliationService(ingestion, events, clock)
    ingestion.register_incident(
        incident_id=incident_id,
        owner_uid=OWNER_UID,
        primary_client_id=PRIMARY_CLIENT_ID,
        rule_version=RULE_VERSION,
    )
    return World(
        clock=clock,
        events=events,
        incidents=incidents,
        grants=grants,
        ingestion=ingestion,
        reconciliation=reconciliation,
        incident_id=incident_id,
    )


@pytest.fixture
def world() -> World:
    return make_world()


@pytest.fixture
def factory() -> Factory:
    return Factory()
