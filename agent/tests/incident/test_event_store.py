"""The event store must be append-only and idempotent by event ID."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from app.services.incident import event_types as et
from app.services.incident.event_store import (
    DuplicateEventError,
    EventStore,
    InMemoryEventStore,
)
from app.services.incident.errors import ServiceError

from .conftest import BASE_TIME


def test_store_exposes_no_update_or_single_delete_operation() -> None:
    """Append-only is structural, not a convention a caller can bypass."""
    surface = {name for name in vars(EventStore) if not name.startswith("_")}
    assert surface == {
        "append",
        "get",
        "list_events",
        "next_sequence",
        "count",
        "purge_expired",
        "contains",
    }
    for forbidden in ("update", "replace", "delete", "set", "patch", "remove"):
        assert not hasattr(InMemoryEventStore, forbidden)


def test_append_assigns_dense_sequences_and_rejects_duplicates(world, factory) -> None:
    result = world.ingest(
        [
            factory.build(et.ACTION_REPORTED, {"action": "cpr_started"}, at=10),
            factory.build(et.ACTION_REPORTED, {"action": "aed_requested"}, at=20),
        ]
    )
    assert [a.server_sequence for a in result.acknowledgements] == [1, 2]
    assert world.events.next_sequence(world.incident_id) == 3

    stored = world.all_events[0]
    with pytest.raises(DuplicateEventError):
        world.events.append(stored)


def test_append_rejects_out_of_band_sequence(world, factory) -> None:
    world.ingest([factory.build(et.ACTION_REPORTED, {"action": "cpr_started"})])
    stored = world.all_events[0]
    gapped = replace(
        stored,
        envelope=replace(
            stored.envelope, event_id="99999999-9999-4999-8999-999999999999"
        ),
        server_sequence=99,
    )
    with pytest.raises(ServiceError) as excinfo:
        world.events.append(gapped)
    assert excinfo.value.reason == "sequence_out_of_band"


def test_list_events_paginates_in_receipt_order(world, factory) -> None:
    world.ingest(
        [
            factory.build(et.ACTION_REPORTED, {"action": f"step_{index}"}, at=index)
            for index in range(5)
        ]
    )
    first = world.events.list_events(world.incident_id, limit=2)
    assert [e.server_sequence for e in first] == [1, 2]
    rest = world.events.list_events(world.incident_id, after_sequence=2)
    assert [e.server_sequence for e in rest] == [3, 4, 5]


def test_events_are_scoped_per_incident(world, factory) -> None:
    from .conftest import make_world

    other = make_world("11111111-2222-4333-8444-555555555555")
    world.ingest([factory.build(et.ACTION_REPORTED, {"action": "cpr_started"})])
    assert world.events.count(world.incident_id) == 1
    assert other.events.count(other.incident_id) == 0
    assert world.events.get(other.incident_id, world.all_events[0].event_id) is None


def test_purge_expired_is_the_only_removal_path(world, factory) -> None:
    world.ingest(
        [
            factory.build(et.ACTION_REPORTED, {"action": "cpr_started"}, at=10),
            factory.build(et.ACTION_REPORTED, {"action": "aed_requested"}, at=20),
        ]
    )
    assert world.events.count(world.incident_id) == 2

    # Retention expiry is one day from receipt by default.
    assert world.events.purge_expired(BASE_TIME + timedelta(hours=1)) == 0
    assert world.events.count(world.incident_id) == 2

    assert world.events.purge_expired(BASE_TIME + timedelta(days=2)) == 2
    assert world.events.count(world.incident_id) == 0


def test_stored_events_are_immutable(world, factory) -> None:
    world.ingest([factory.build(et.ACTION_REPORTED, {"action": "cpr_started"})])
    stored = world.all_events[0]
    with pytest.raises(Exception):
        stored.envelope.detail = {"action": "tampered"}  # type: ignore[misc]

    # Mutating the dict returned by ``to_dict`` cannot reach stored history.
    snapshot = stored.to_dict()
    snapshot["detail"]["action"] = "tampered"
    assert world.all_events[0].detail["action"] == "cpr_started"
