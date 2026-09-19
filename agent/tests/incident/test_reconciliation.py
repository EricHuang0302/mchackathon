"""Reconnect reconciliation: duplicates, resume, ordering, mode preservation."""

from __future__ import annotations

import pytest

from app.services.incident import ROLE_AED_RUNNER, ServiceError
from app.services.incident import event_types as et
from app.services.incident.errors import STALE_REVISION, UNAUTHORIZED
from app.services.incident.reconciliation import ResyncRequest

from .conftest import PRIMARY_CLIENT_ID, PRIMARY_INSTANCE_ID, Factory


def resync(world, **kwargs):
    request = ResyncRequest(
        client_id=kwargs.pop("client_id", PRIMARY_CLIENT_ID),
        client_instance_id=kwargs.pop("client_instance_id", PRIMARY_INSTANCE_ID),
        interaction_mode=kwargs.pop("interaction_mode", "call_119"),
        mode_revision=kwargs.pop("mode_revision", 0),
        authority_epoch=kwargs.pop("authority_epoch", 0),
        **kwargs,
    )
    return world.reconciliation.reconcile(
        world.incident_id, request, principal=world.primary
    )


def test_a_replayed_offline_batch_changes_nothing(world, factory) -> None:
    payloads = [
        factory.build(et.ACTION_REPORTED, {"action": "cpr_started"}, at=10, source="button"),
        factory.build(et.OBSERVATION_CONFIRMED, {"key": "patient.breathing", "value": False}, at=20),
    ]
    first = resync(world, events=payloads)
    count_after_first = world.events.count(world.incident_id)
    revision_after_first = first.snapshot.snapshot_revision

    second = resync(world, events=payloads)

    assert [a.status for a in first.acknowledgements] == ["accepted", "accepted"]
    assert [a.status for a in second.acknowledgements] == ["duplicate", "duplicate"]
    assert world.events.count(world.incident_id) == count_after_first
    assert second.snapshot.snapshot_revision == revision_after_first


def test_an_interrupted_upload_resumes_from_the_next_sequence(world, factory) -> None:
    payloads = [
        factory.build(et.ACTION_REPORTED, {"action": f"step_{index}"}, at=index, source="button")
        for index in range(6)
    ]
    partial = resync(world, events=payloads[:3])
    assert partial.resume_from_client_sequence == 4

    completed = resync(world, events=payloads[3:])
    assert completed.resume_from_client_sequence == 7
    assert world.events.count(world.incident_id) == 6


def test_out_of_order_local_events_project_in_occurrence_order(world, factory) -> None:
    early = factory.build(et.OBSERVATION_CONFIRMED, {"key": "location.floor", "value": "2F"}, at=10)
    late = factory.build(et.OBSERVATION_CONFIRMED, {"key": "location.floor", "value": "5F"}, at=90)

    # The later occurrence is uploaded first.
    result = resync(world, events=[late, early])

    assert len(result.accepted) == 2
    # Receipt order put "2F" last, but occurrence order puts "5F" last.
    assert result.snapshot.field_for("location.floor").value == "5F"


def test_a_stale_revision_conflicts_without_overwriting_state(world, factory) -> None:
    world.ingest([factory.build(et.MODE_CHANGED, {"mode": "voice_guidance", "modeRevision": 3}, at=5)])

    stale_factory = Factory(namespace="stale")
    stale_factory.mode_revision = 1
    result = resync(
        world,
        interaction_mode="voice_guidance",
        mode_revision=3,
        events=[stale_factory.build(et.MODE_CHANGED, {"mode": "call_119", "modeRevision": 2}, at=6)],
    )

    reasons = [c.reason for c in result.conflicts]
    assert "mode_revision_not_advancing" in reasons
    assert result.interaction_mode == "voice_guidance"
    assert result.mode_revision == 3


def test_reconnect_never_returns_a_mode_revision_behind_the_client(world) -> None:
    result = resync(world, interaction_mode="on_call", mode_revision=4)

    assert result.mode_revision == 4
    assert result.interaction_mode == "on_call"
    assert result.mode_preserved is True
    conflict = next(c for c in result.conflicts if c.reason == "server_mode_revision_behind_client")
    assert conflict.code == STALE_REVISION
    assert conflict.detail["serverModeRevision"] == 0


def test_a_newer_server_mode_is_returned_when_the_client_is_behind(world, factory) -> None:
    world.ingest([factory.build(et.MODE_CHANGED, {"mode": "handover", "modeRevision": 7}, at=5)])
    result = resync(world, interaction_mode="on_call", mode_revision=2)

    assert result.mode_revision == 7
    assert result.interaction_mode == "handover"
    assert result.mode_preserved is False
    assert not [c for c in result.conflicts if c.reason == "server_mode_revision_behind_client"]


@pytest.mark.parametrize("local_mode", ["call_119", "on_call", "handover"])
def test_reconnect_never_uses_server_voice_to_unmute_a_silent_local_mode(
    world, factory, local_mode
) -> None:
    world.ingest(
        [
            factory.build(
                et.MODE_CHANGED,
                {"mode": "voice_guidance", "modeRevision": 7},
                at=5,
            )
        ]
    )

    result = resync(world, interaction_mode=local_mode, mode_revision=2)

    assert result.interaction_mode == local_mode
    assert result.mode_revision == 2
    assert result.mode_preserved is True
    assert any(
        conflict.reason
        in {"server_mode_would_unsafely_unmute_client", "local_handover_preserved"}
        for conflict in result.conflicts
    )


def test_equal_mode_revision_with_different_values_is_a_conflict(world, factory) -> None:
    world.ingest(
        [factory.build(et.MODE_CHANGED, {"mode": "on_call", "modeRevision": 2}, at=5)]
    )

    result = resync(world, interaction_mode="call_119", mode_revision=2)

    assert result.interaction_mode == "call_119"
    assert result.mode_preserved is True
    conflict = next(c for c in result.conflicts if c.reason == "mode_revision_diverged")
    assert conflict.code == STALE_REVISION


def test_the_primary_may_advance_its_authority_epoch_on_reconnect(world) -> None:
    result = resync(world, authority_epoch=3)
    assert result.authority_epoch == 3
    assert world.incident.authority_epoch == 3


def test_another_client_cannot_advance_the_authority_epoch(world) -> None:
    with pytest.raises(ServiceError) as excinfo:
        resync(world, client_id="second-tab-client", authority_epoch=9)
    assert (excinfo.value.code, excinfo.value.reason) == (
        UNAUTHORIZED,
        "primary_client_mismatch",
    )


def test_helper_cannot_use_primary_reconciliation_to_read_clinical_state(world) -> None:
    helper = world.principal_for("runner-uid", ROLE_AED_RUNNER, helper_id="runner-1")
    request = ResyncRequest(
        client_id="runner-client",
        client_instance_id="runner-tab",
        interaction_mode="on_call",
        mode_revision=0,
        authority_epoch=0,
    )

    with pytest.raises(ServiceError) as excinfo:
        world.reconciliation.reconcile(
            world.incident_id, request, principal=helper
        )
    assert (excinfo.value.code, excinfo.value.reason) == (
        UNAUTHORIZED,
        "reconciliation_requires_primary",
    )


def test_catch_up_returns_events_the_client_has_not_seen(world, factory) -> None:
    helper = world.principal_for("runner-uid", ROLE_AED_RUNNER, helper_id="runner-1")
    helper_factory = Factory(namespace="runner", client_id="runner-client", client_instance_id="runner-tab")
    world.ingest(
        [
            helper_factory.build(
                et.HELPER_UPDATED,
                {"helperId": "runner-1", "status": "en_route"},
                at=10,
                source="helper_report",
            ),
            helper_factory.build(
                et.HELPER_UPDATED,
                {"helperId": "runner-1", "status": "unavailable", "reason": "cabinet_locked"},
                at=20,
                source="helper_report",
            ),
        ],
        principal=helper,
    )

    result = resync(world, known_server_sequence=0)

    assert [e.server_sequence for e in result.replay_events] == [1, 2]
    assert result.catch_up_complete is True
    # Replay updates records and projections; it never re-executes anything.
    assert result.replay_execution_allowed is False

    caught_up = resync(world, known_server_sequence=2)
    assert caught_up.replay_events == ()


def test_catch_up_is_bounded_and_says_so(world, factory) -> None:
    from app.services.incident.reconciliation import ReconciliationService

    bounded = ReconciliationService(world.ingestion, world.events, world.clock, max_replay=2)
    world.ingest(
        [
            factory.build(et.ACTION_REPORTED, {"action": f"step_{index}"}, at=index, source="button")
            for index in range(5)
        ]
    )
    result = bounded.reconcile(
        world.incident_id,
        ResyncRequest(
            client_id=PRIMARY_CLIENT_ID,
            client_instance_id=PRIMARY_INSTANCE_ID,
            interaction_mode="call_119",
            mode_revision=0,
            authority_epoch=0,
        ),
        principal=world.primary,
    )
    assert len(result.replay_events) == 2
    assert result.catch_up_complete is False


def test_the_projection_catches_up_with_the_accepted_events(world, factory) -> None:
    result = resync(
        world,
        events=[
            factory.build(et.OBSERVATION_CONFIRMED, {"key": "patient.responsive", "value": False}, at=10),
            factory.build(et.ACTION_REPORTED, {"action": "cpr_started"}, at=20, source="button"),
        ],
    )
    assert result.snapshot.snapshot_revision == 2
    assert result.snapshot.generated_through_sequence == 2
    assert result.snapshot.field_for("patient.responsive").value is False


def test_an_unknown_interaction_mode_is_refused(world) -> None:
    with pytest.raises(ServiceError) as excinfo:
        resync(world, interaction_mode="speakerphone")
    assert excinfo.value.reason == "unknown_interaction_mode"


def test_reconcile_result_serializes_to_json_shaped_data(world, factory) -> None:
    result = resync(world, events=[factory.build(et.ACTION_REPORTED, {"action": "cpr_started"}, at=10, source="button")])
    payload = result.to_dict()
    assert payload["replayExecutionAllowed"] is False
    assert payload["sceneSnapshot"]["snapshotRevision"] == 1
    assert payload["incident"]["interactionMode"] == "call_119"
