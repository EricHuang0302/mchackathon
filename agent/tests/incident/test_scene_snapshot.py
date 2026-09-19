"""Scene-snapshot projection: determinism, provenance, precedence, freshness."""

from __future__ import annotations

import itertools
from datetime import timedelta

from app.services.incident import event_types as et
from app.services.incident import project_scene_snapshot
from app.services.incident.scene_snapshot import AGING, FRESH, STALE, FreshnessPolicy

from .conftest import BASE_TIME, Factory, make_world


def build_payloads(namespace: str = "test") -> list[dict]:
    """A fixed event set used to compare projections across arrival orders."""
    factory = Factory(namespace=namespace)
    return [
        factory.build(
            et.OBSERVATION_CONFIRMED,
            {"key": "location.address", "value": "Example Road 1"},
            at=10,
        ),
        factory.build(
            et.OBSERVATION_CONFIRMED,
            {"key": "patient.responsive", "value": False},
            at=20,
        ),
        factory.build(
            et.OBSERVATION_PROPOSED,
            {"key": "hazards.description", "value": "wet floor"},
            at=30,
            source="camera_proposal",
        ),
        factory.build(et.ACTION_REPORTED, {"action": "cpr_started"}, at=40, source="button"),
        factory.build(
            et.OBSERVATION_CONFIRMED,
            {"key": "patient.breathing", "value": False},
            at=50,
        ),
    ]


def project(world, **kwargs):
    return project_scene_snapshot(
        world.incident, world.all_events, now=world.now(), **kwargs
    )


def content_only(snapshot) -> dict:
    """Snapshot content without the receipt-time fields.

    ``receivedAt``, ``updatedAt`` and the server-sequence boundary genuinely
    depend on upload order. Everything else is a function of the event set.
    """
    payload = snapshot.to_dict()
    for section in payload["sections"].values():
        for item in section:
            item["provenance"].pop("receivedAt", None)
    for key in ("updatedAt", "expiresAt", "generatedThroughSequence", "generatedThroughEventId"):
        payload.pop(key, None)
    return payload


def test_projection_is_invariant_across_arrival_orders() -> None:
    payloads = build_payloads()
    reference = None
    for index, order in enumerate(itertools.permutations(range(len(payloads)))):
        if index % 23:  # sample the permutation space deterministically
            continue
        world = make_world()
        for position in order:
            world.ingest([payloads[position]])
        summary = content_only(project(world))
        if reference is None:
            reference = summary
        else:
            assert summary == reference


def test_one_by_one_upload_matches_a_single_batch() -> None:
    payloads = build_payloads()

    batched = make_world()
    batched.ingest(payloads)

    streamed = make_world()
    for payload in payloads:
        streamed.ingest([payload])

    assert content_only(project(batched)) == content_only(project(streamed))
    assert project(batched).snapshot_revision == project(streamed).snapshot_revision


def test_unobserved_fields_stay_unknown_and_are_never_false(world, factory) -> None:
    world.ingest([factory.build(et.OBSERVATION_CONFIRMED, {"key": "patient.responsive", "value": False}, at=10)])
    snapshot = project(world)

    breathing = snapshot.field_for("patient.breathing")
    assert breathing.value is None
    assert breathing.provenance.confirmation == et.UNKNOWN
    assert breathing.is_unknown
    assert breathing.provenance.evidence_event_ids == ()

    responsive = snapshot.field_for("patient.responsive")
    assert responsive.value is False
    assert responsive.provenance.confirmation == "confirmed"


def test_every_allowlisted_key_appears_in_its_section(world) -> None:
    snapshot = project(world)
    rendered = {
        item.key
        for section in et.SNAPSHOT_SECTIONS
        for item in snapshot.sections[section]
    }
    assert rendered == set(et.OBSERVATION_KEYS)


def test_a_proposal_cannot_overwrite_a_confirmed_fact(world, factory) -> None:
    world.ingest(
        [
            factory.build(et.OBSERVATION_CONFIRMED, {"key": "patient.breathing", "value": False}, at=10),
            factory.build(
                et.OBSERVATION_PROPOSED,
                {"key": "patient.breathing", "value": True},
                at=20,
                source="camera_proposal",
            ),
            factory.build(
                et.OBSERVATION_PROPOSED,
                {"key": "patient.breathing", "value": True},
                at=30,
                source="model_proposal",
            ),
        ]
    )
    field = project(world).field_for("patient.breathing")

    assert field.value is False
    assert field.provenance.confirmation == "confirmed"
    assert field.provenance.source == "user_report"
    # The contradiction is retained for explicit confirmation, not discarded.
    assert [p["value"] for p in field.pending_proposals] == [True, True]
    assert [p["source"] for p in field.pending_proposals] == [
        "camera_proposal",
        "model_proposal",
    ]
    assert project(world).snapshot_revision == 3


def test_a_confirmation_upgrades_a_previous_proposal(world, factory) -> None:
    proposal = factory.build(
        et.OBSERVATION_PROPOSED,
        {"key": "location.address", "value": "Example Road 1"},
        at=10,
        source="geocoder",
    )
    world.ingest([proposal])
    assert project(world).field_for("location.address").provenance.confirmation == "proposed"

    world.ingest(
        [
            factory.build(
                et.OBSERVATION_CONFIRMED,
                {
                    "key": "location.address",
                    "value": "Example Road 1",
                    "evidenceEventIds": [proposal["eventId"]],
                },
                at=20,
            )
        ]
    )
    field = project(world).field_for("location.address")
    assert field.provenance.confirmation == "confirmed"
    assert proposal["eventId"] in field.provenance.evidence_event_ids


def test_a_later_report_replaces_an_equally_ranked_earlier_one(world, factory) -> None:
    world.ingest(
        [
            factory.build(et.OBSERVATION_CONFIRMED, {"key": "location.floor", "value": "2F"}, at=10),
            factory.build(et.OBSERVATION_CONFIRMED, {"key": "location.floor", "value": "3F"}, at=20),
        ]
    )
    assert project(world).field_for("location.floor").value == "3F"


def test_a_correction_can_fix_a_confirmed_fact(world, factory) -> None:
    original = factory.build(
        et.OBSERVATION_CONFIRMED, {"key": "people.bystanderCount", "value": 12}, at=10
    )
    world.ingest([original])
    correction = factory.build(
        et.EVENT_CORRECTED,
        {"correctsEventId": original["eventId"], "reason": "mistyped", "detail": {"value": 2}},
        at=20,
    )
    world.ingest([correction])

    field = project(world).field_for("people.bystanderCount")
    assert field.value == 2
    assert field.provenance.confirmation == "confirmed"
    assert field.provenance.corrected_from_event_ids == (correction["eventId"],)
    assert project(world).snapshot_revision == 2
    # History is intact: the original event is still stored unmodified.
    assert world.events.get(world.incident_id, original["eventId"]).detail["value"] == 12


def test_a_chain_of_corrections_resolves_to_the_last_one(world, factory) -> None:
    original = factory.build(
        et.OBSERVATION_CONFIRMED, {"key": "people.bystanderCount", "value": 12}, at=10
    )
    world.ingest([original])
    first = factory.build(
        et.EVENT_CORRECTED,
        {"correctsEventId": original["eventId"], "detail": {"value": 5}},
        at=20,
    )
    world.ingest([first])
    second = factory.build(
        et.EVENT_CORRECTED,
        {"correctsEventId": first["eventId"], "detail": {"value": 2}},
        at=30,
    )
    world.ingest([second])

    field = project(world).field_for("people.bystanderCount")
    assert field.value == 2
    assert set(field.provenance.corrected_from_event_ids) == {
        first["eventId"],
        second["eventId"],
    }


def test_a_retracted_action_is_marked_not_deleted(world, factory) -> None:
    action = factory.build(et.ACTION_REPORTED, {"action": "cpr_started"}, at=10, source="button")
    world.ingest([action])
    world.ingest(
        [
            factory.build(
                et.EVENT_CORRECTED,
                {"correctsEventId": action["eventId"], "retracted": True, "reason": "mistap"},
                at=20,
            )
        ]
    )
    actions = project(world).actions_performed
    assert [a.action for a in actions] == ["cpr_started"]
    assert actions[0].retracted is True


def test_reported_actions_are_separate_from_commands_and_decisions(world, factory) -> None:
    world.ingest(
        [
            factory.build(
                et.DECISION_COMMITTED,
                {"toState": "cpr", "reasonCode": "no_breathing", "stateRevision": 1},
                at=10,
                source="rule_engine",
            ),
            factory.build(
                et.COMMAND_ISSUED,
                {"commandId": "cmd-1", "command": "start_metronome"},
                at=11,
                source="rule_engine",
            ),
            factory.build(
                et.COMMAND_ACKNOWLEDGED,
                {"commandId": "cmd-1", "result": "started"},
                at=12,
                source="device",
            ),
        ]
    )
    snapshot = project(world)
    # An instruction and a device acknowledgement are not a performed action.
    assert snapshot.actions_performed == ()

    world.ingest([factory.build(et.ACTION_REPORTED, {"action": "cpr_started"}, at=20, source="button")])
    assert [a.action for a in project(world).actions_performed] == ["cpr_started"]


def test_freshness_uses_the_injected_clock(world, factory) -> None:
    world.ingest([factory.build(et.OBSERVATION_CONFIRMED, {"key": "patient.responsive", "value": False}, at=0)])
    policy = FreshnessPolicy()

    assert project(world, policy=policy).field_for("patient.responsive").freshness == FRESH

    world.clock.advance(120)
    aging = project(world, policy=policy).field_for("patient.responsive")
    assert aging.freshness == AGING
    assert aging.age_seconds == 120

    world.clock.advance(600)
    assert project(world, policy=policy).field_for("patient.responsive").freshness == STALE


def test_observed_time_may_differ_from_client_time(world, factory) -> None:
    world.ingest(
        [
            factory.build(
                et.OBSERVATION_CONFIRMED,
                {
                    "key": "circumstances.occurredAt",
                    "value": "2026-09-19T07:55:00Z",
                    "observedAt": "2026-09-19T07:55:00Z",
                },
                at=300,
            )
        ]
    )
    field = project(world).field_for("circumstances.occurredAt")
    assert field.provenance.observed_at == BASE_TIME - timedelta(minutes=5)


def test_client_time_uncertainty_is_carried_into_provenance(world, factory) -> None:
    payload = factory.build(
        et.OBSERVATION_CONFIRMED, {"key": "patient.responsive", "value": False}, at=10
    )
    payload["clientTimeUncertain"] = True
    world.ingest([payload])
    assert project(world).field_for("patient.responsive").provenance.observed_time_uncertain


def test_snapshot_revision_counts_content_changes_only(world, factory) -> None:
    assert project(world).snapshot_revision == 0

    world.ingest([factory.build(et.OBSERVATION_CONFIRMED, {"key": "patient.responsive", "value": False}, at=10)])
    assert project(world).snapshot_revision == 1

    # A mode change is not scene content.
    world.ingest([factory.build(et.MODE_CHANGED, {"mode": "on_call", "modeRevision": 1}, at=20)])
    assert project(world).snapshot_revision == 1

    world.ingest([factory.build(et.OBSERVATION_CONFIRMED, {"key": "patient.breathing", "value": False}, at=30)])
    assert project(world).snapshot_revision == 2


def test_generated_through_revision_is_distinct_from_snapshot_revision(world, factory) -> None:
    world.ingest(
        [
            factory.build(et.OBSERVATION_CONFIRMED, {"key": "patient.responsive", "value": False}, at=10),
            factory.build(
                et.INCIDENT_STATE_UPDATED,
                {"clinicalState": "assessment", "stateRevision": 4},
                at=20,
            ),
        ]
    )
    snapshot = project(world)
    assert snapshot.snapshot_revision == 1
    assert snapshot.generated_through_revision == 4
    assert snapshot.generated_through_sequence == 2
    assert snapshot.generated_through_event_id == world.all_events[1].event_id


def test_projection_catches_up_in_bounded_steps(world, factory) -> None:
    world.ingest(
        [
            factory.build(et.OBSERVATION_CONFIRMED, {"key": "patient.responsive", "value": False}, at=10),
            factory.build(et.OBSERVATION_CONFIRMED, {"key": "patient.breathing", "value": False}, at=20),
            factory.build(et.ACTION_REPORTED, {"action": "cpr_started"}, at=30, source="button"),
        ]
    )
    lagging = project(world, through_sequence=1)
    assert lagging.snapshot_revision == 1
    assert lagging.generated_through_sequence == 1
    assert lagging.field_for("patient.breathing").is_unknown

    caught_up = project(world, through_sequence=3)
    assert caught_up.snapshot_revision == 3
    assert caught_up.field_for("patient.breathing").value is False
    # Replaying the same boundary does not bump the revision.
    assert project(world, through_sequence=3).snapshot_revision == 3


def test_source_event_boundary_matches_the_maximum_server_sequence(
    world, factory
) -> None:
    later_occurrence = factory.build(
        et.OBSERVATION_CONFIRMED,
        {"key": "location.floor", "value": "5F"},
        at=90,
    )
    earlier_occurrence = factory.build(
        et.OBSERVATION_CONFIRMED,
        {"key": "location.address", "value": "Synthetic Road 1"},
        at=10,
    )
    # The older occurrence is received last and therefore defines the source
    # event boundary even though it is not last in clinical projection order.
    world.ingest([later_occurrence, earlier_occurrence])

    snapshot = project(world)

    assert snapshot.generated_through_sequence == 2
    assert snapshot.generated_through_event_id == earlier_occurrence["eventId"]
