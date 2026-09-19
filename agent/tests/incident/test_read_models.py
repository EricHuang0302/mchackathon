"""Authorized snapshot, MIST and handoff read-model service."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from app.services.incident import (
    AccessGrant,
    InMemoryEventStore,
    IncidentReadModelService,
    ROLE_AED_RUNNER,
    ROLE_AMBULANCE_GREETER,
    ROLE_EMS_VIEWER,
    ServiceError,
)
from app.services.incident import event_types as et

from .conftest import BASE_TIME


def service_for(world) -> IncidentReadModelService:
    return IncidentReadModelService(
        world.incidents,
        world.events,
        world.grants,
        world.clock,
    )


def grant(world, *, uid: str, role: str) -> None:
    world.grants.put(
        AccessGrant(
            grant_id=f"grant-{uid}",
            incident_id=world.incident_id,
            uid=uid,
            scope=role,
            helper_id=f"helper-{uid}" if role != ROLE_EMS_VIEWER else None,
            expires_at=BASE_TIME + timedelta(hours=1),
        )
    )


def test_handoff_uses_one_snapshot_boundary(world, factory) -> None:
    world.ingest(
        [
            factory.build(
                et.OBSERVATION_CONFIRMED,
                {"key": "patient.breathing", "value": False},
                at=10,
            ),
            factory.build(et.ACTION_REPORTED, {"action": "cpr_started"}, at=20),
        ]
    )
    grant(world, uid="ems", role=ROLE_EMS_VIEWER)

    handoff = service_for(world).handoff(incident_id=world.incident_id, uid="ems")

    assert handoff.snapshot.snapshot_revision == handoff.mist.snapshot_revision
    assert (
        handoff.snapshot.generated_through_sequence
        == handoff.mist.generated_through_sequence
        == handoff.timeline.generated_through_sequence
    )
    assert handoff.snapshot.field_for("patient.breathing").value is False
    assert [action.action for action in handoff.mist.reported_actions] == ["cpr_started"]


def test_greeter_can_read_snapshot_but_not_mist_or_timeline(world) -> None:
    grant(world, uid="greeter", role=ROLE_AMBULANCE_GREETER)
    service = service_for(world)

    assert service.scene_snapshot(incident_id=world.incident_id, uid="greeter")
    with pytest.raises(ServiceError) as mist_error:
        service.mist(incident_id=world.incident_id, uid="greeter")
    with pytest.raises(ServiceError) as timeline_error:
        service.timeline(incident_id=world.incident_id, uid="greeter")

    assert mist_error.value.reason == "capability_denied"
    assert timeline_error.value.reason == "capability_denied"


def test_runner_cannot_read_clinical_projection(world) -> None:
    grant(world, uid="runner", role=ROLE_AED_RUNNER)

    with pytest.raises(ServiceError) as error:
        service_for(world).scene_snapshot(incident_id=world.incident_id, uid="runner")

    assert error.value.reason == "capability_denied"


def test_expired_grant_is_checked_before_projection(world) -> None:
    world.grants.put(
        AccessGrant(
            grant_id="expired",
            incident_id=world.incident_id,
            uid="ems",
            scope=ROLE_EMS_VIEWER,
            expires_at=BASE_TIME,
        )
    )

    with pytest.raises(ServiceError) as error:
        service_for(world).scene_snapshot(incident_id=world.incident_id, uid="ems")

    assert (error.value.code, error.value.reason) == ("expired", "grant_expired")


def test_expired_incident_is_not_projected_for_owner(world) -> None:
    world.clock.set(world.incident.expires_at)

    with pytest.raises(ServiceError) as error:
        service_for(world).scene_snapshot(
            incident_id=world.incident_id,
            uid=world.incident.owner_uid,
        )

    assert (error.value.code, error.value.reason) == ("expired", "incident_expired")


def test_expired_events_are_withheld_before_async_cleanup(world, factory) -> None:
    world.ingest(
        [
            factory.build(
                et.OBSERVATION_CONFIRMED,
                {"key": "patient.breathing", "value": False},
            )
        ]
    )
    retained = InMemoryEventStore()
    retained.append(
        replace(world.all_events[0], expires_at=BASE_TIME + timedelta(seconds=30))
    )
    world.clock.advance(31)
    service = IncidentReadModelService(
        world.incidents,
        retained,
        world.grants,
        world.clock,
    )

    snapshot = service.scene_snapshot(
        incident_id=world.incident_id,
        uid=world.incident.owner_uid,
    )
    timeline = service.timeline(
        incident_id=world.incident_id,
        uid=world.incident.owner_uid,
    )

    assert snapshot.field_for("patient.breathing").value is None
    assert timeline.entries == ()


def test_handoff_cursor_pins_pages_to_the_first_boundary(world, factory) -> None:
    for index in range(3):
        world.ingest(
            [
                factory.build(
                    et.ACTION_REPORTED,
                    {"action": f"action_{index}"},
                    at=index,
                )
            ]
        )
    grant(world, uid="ems", role=ROLE_EMS_VIEWER)
    service = service_for(world)
    first = service.handoff(
        incident_id=world.incident_id,
        uid="ems",
        page_size=2,
    )
    assert first.timeline.next_cursor == "window:3:2"

    world.ingest(
        [factory.build(et.ACTION_REPORTED, {"action": "new_after_page_one"}, at=10)]
    )
    second = service.handoff(
        incident_id=world.incident_id,
        uid="ems",
        cursor=first.timeline.next_cursor,
        page_size=2,
    )

    assert [entry.detail["action"] for entry in second.timeline.entries] == ["action_2"]
    assert second.snapshot.generated_through_sequence == 3
    assert second.mist.generated_through_sequence == 3
    assert second.timeline.generated_through_sequence == 3


@pytest.mark.parametrize(
    "cursor",
    ["seq:1", "window:2:3", "window:2:²", f"window:{'9' * 5000}:1"],
)
def test_read_model_rejects_malformed_window_cursor(world, cursor) -> None:
    with pytest.raises(ServiceError) as error:
        service_for(world).timeline(
            incident_id=world.incident_id,
            uid=world.incident.owner_uid,
            cursor=cursor,
        )

    assert error.value.reason == "malformed_cursor"
