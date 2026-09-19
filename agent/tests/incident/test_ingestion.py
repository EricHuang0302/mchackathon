"""Batch ingestion: idempotency, revision checks, corrections, authorization."""

from __future__ import annotations

import pytest

from app.services.incident import ROLE_AED_RUNNER, ROLE_EMS_VIEWER, ServiceError
from app.services.incident import event_types as et
from app.services.incident.errors import (
    INVALID_INPUT,
    RULE_MISMATCH,
    STALE_REVISION,
    UNAUTHORIZED,
)

from .conftest import PRIMARY_CLIENT_ID, Factory


def only_conflict(result):
    assert len(result.conflicts) == 1, result.conflicts
    return result.conflicts[0]


# -- validation ------------------------------------------------------------


def test_unknown_event_type_is_rejected_without_blocking_the_batch(world, factory):
    good = factory.build(et.ACTION_REPORTED, {"action": "cpr_started"}, at=1)
    bad = factory.build(et.ACTION_REPORTED, {"action": "x"}, at=2)
    bad["type"] = "action.invented"
    after = factory.build(et.ACTION_REPORTED, {"action": "aed_requested"}, at=3)

    result = world.ingest([good, bad, after])

    assert [a.event_id for a in result.accepted] == [good["eventId"], after["eventId"]]
    conflict = only_conflict(result)
    assert (conflict.code, conflict.reason) == (INVALID_INPUT, "unknown_event_type")


def test_server_projected_event_type_cannot_be_client_submitted(world, factory):
    result = world.ingest(
        [factory.build(et.SCENE_SNAPSHOT_UPDATED, {"snapshotRevision": 9})]
    )
    conflict = only_conflict(result)
    assert conflict.reason == "server_projected_event_type"
    assert world.events.count(world.incident_id) == 0


@pytest.mark.parametrize(
    "field, value, reason",
    [
        ("eventId", "not-a-uuid", "malformed_identifier"),
        ("clientSequence", 0, "integer_below_minimum"),
        ("clientSequence", "3", "expected_integer"),
        ("clientTime", "2026-09-19T08:00:00", "malformed_timestamp"),
        ("clientId", "", "expected_non_empty_string"),
        ("ruleVersion", "", "expected_non_empty_string"),
        ("source", "telepathy", "unknown_source"),
        ("authorityEpoch", -1, "integer_below_minimum"),
    ],
)
def test_envelope_validation(world, factory, field, value, reason):
    payload = factory.build(et.ACTION_REPORTED, {"action": "cpr_started"})
    payload[field] = value
    conflict = only_conflict(world.ingest([payload]))
    assert (conflict.code, conflict.reason) == (INVALID_INPUT, reason)


def test_batch_size_is_bounded(world, factory):
    payloads = [
        factory.build(et.ACTION_REPORTED, {"action": f"a{index}"}, at=index)
        for index in range(201)
    ]
    with pytest.raises(ServiceError) as excinfo:
        world.ingest(payloads)
    assert excinfo.value.reason == "batch_too_large"
    assert world.events.count(world.incident_id) == 0


# -- idempotency -----------------------------------------------------------


def test_replayed_batch_returns_identical_acknowledgements(world, factory):
    payloads = [
        factory.build(et.ACTION_REPORTED, {"action": "cpr_started"}, at=10),
        factory.build(et.OBSERVATION_CONFIRMED, {"key": "patient.responsive", "value": False}, at=20),
    ]
    first = world.ingest(payloads)
    revision_before = world.incident.state_revision

    world.clock.advance(120)
    second = world.ingest(payloads)

    assert [a.status for a in first.acknowledgements] == ["accepted", "accepted"]
    assert [a.status for a in second.acknowledgements] == ["duplicate", "duplicate"]
    # A duplicate returns the original receipt facts, not the retry's.
    assert [a.to_dict() | {"status": "accepted"} for a in second.acknowledgements] == [
        a.to_dict() for a in first.acknowledgements
    ]
    assert world.events.count(world.incident_id) == 2
    assert world.incident.state_revision == revision_before


def test_reused_event_id_with_different_content_is_rejected(world, factory):
    original = factory.build(et.ACTION_REPORTED, {"action": "cpr_started"}, at=10)
    world.ingest([original])

    impostor = dict(original)
    impostor["detail"] = {"action": "bleeding_controlled"}
    conflict = only_conflict(world.ingest([impostor]))

    assert conflict.reason == "event_id_reused_for_different_content"
    assert world.all_events[0].detail["action"] == "cpr_started"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("clientInstanceId", "another-tab"),
        ("clientSequence", 99),
        ("clientTimeUncertain", True),
        ("authorityEpoch", 4),
        ("stateRevision", 3),
        ("modeRevision", 2),
        ("ruleVersion", "demo-v2"),
        ("source", "button"),
    ],
)
def test_reused_event_id_must_match_the_complete_envelope(
    world, factory, field, value
):
    original = factory.build(et.ACTION_REPORTED, {"action": "cpr_started"}, at=10)
    world.ingest([original])
    impostor = dict(original)
    impostor[field] = value

    conflict = only_conflict(world.ingest([impostor]))

    assert conflict.reason == "event_id_reused_for_different_content"
    assert world.events.count(world.incident_id) == 1


# -- revision and epoch checks ---------------------------------------------


def test_pinned_rule_version_mismatch(world, factory):
    payload = factory.build(et.ACTION_REPORTED, {"action": "cpr_started"})
    payload["ruleVersion"] = "demo-v2"
    conflict = only_conflict(world.ingest([payload]))
    assert (conflict.code, conflict.reason) == (RULE_MISMATCH, "pinned_rule_version_mismatch")


def test_mode_revision_must_advance(world, factory):
    world.ingest([factory.build(et.MODE_CHANGED, {"mode": "on_call", "modeRevision": 1}, at=1)])
    assert world.incident.interaction_mode == "on_call"

    conflict = only_conflict(
        world.ingest(
            [factory.build(et.MODE_CHANGED, {"mode": "call_119", "modeRevision": 1}, at=2)]
        )
    )
    assert (conflict.code, conflict.reason) == (STALE_REVISION, "mode_revision_not_advancing")
    assert world.incident.interaction_mode == "on_call"
    assert world.incident.mode_revision == 1


def test_call_report_does_not_move_interaction_mode(world, factory):
    world.ingest([factory.build(et.MODE_CHANGED, {"mode": "on_call", "modeRevision": 1}, at=1)])
    world.ingest([factory.build(et.CALL_REPORTED, {"reportedState": "call_ended"}, at=2)])

    incident = world.incident
    assert incident.interaction_mode == "on_call"
    assert incident.call_status["reportedState"] == "call_ended"
    assert incident.call_status["delegatedCallActive"] is False


def test_unknown_call_report_state_is_rejected(world, factory):
    conflict = only_conflict(
        world.ingest([factory.build(et.CALL_REPORTED, {"reportedState": "connected"})])
    )
    assert conflict.reason == "unknown_call_report_state"


def test_call_report_does_not_coerce_a_non_boolean_delegated_state(world, factory):
    conflict = only_conflict(
        world.ingest(
            [
                factory.build(
                    et.CALL_REPORTED,
                    {
                        "reportedState": "delegated_call_active",
                        "delegatedCallActive": "false",
                    },
                )
            ]
        )
    )
    assert (conflict.code, conflict.reason) == (INVALID_INPUT, "expected_boolean")


def test_decision_requires_matching_expected_state_revision(world, factory):
    world.ingest(
        [factory.build(et.INCIDENT_STATE_UPDATED, {"clinicalState": "assessment", "stateRevision": 1}, at=1)]
    )
    conflict = only_conflict(
        world.ingest(
            [
                factory.build(
                    et.DECISION_COMMITTED,
                    {
                        "fromState": "assessment",
                        "toState": "cpr",
                        "reasonCode": "no_breathing",
                        "expectedStateRevision": 0,
                        "stateRevision": 2,
                    },
                    at=2,
                    source="rule_engine",
                )
            ]
        )
    )
    assert (conflict.code, conflict.reason) == (
        STALE_REVISION,
        "decision_expected_state_revision_mismatch",
    )
    assert world.incident.clinical_state == "assessment"


def test_stale_authority_epoch_is_rejected_and_primary_may_advance(world, factory):
    factory.authority_epoch = 2
    world.ingest([factory.build(et.ACTION_REPORTED, {"action": "cpr_started"}, at=1)])
    assert world.incident.authority_epoch == 2

    factory.authority_epoch = 1
    conflict = only_conflict(
        world.ingest([factory.build(et.ACTION_REPORTED, {"action": "aed_requested"}, at=2)])
    )
    assert (conflict.code, conflict.reason) == (STALE_REVISION, "authority_epoch_stale")
    assert world.incident.authority_epoch == 2


def test_second_writer_cannot_advance_the_authority_epoch(world, factory):
    other = Factory(namespace="other", client_id="second-tab-client", client_instance_id="second-tab")
    other.authority_epoch = 5
    conflict = only_conflict(
        world.ingest([other.build(et.ACTION_REPORTED, {"action": "cpr_started"}, at=1)])
    )
    assert (conflict.code, conflict.reason) == (
        UNAUTHORIZED,
        "non_primary_authority_epoch_advance",
    )
    assert world.incident.authority_epoch == 0


# -- corrections -----------------------------------------------------------


def test_correction_appends_and_leaves_the_original_untouched(world, factory):
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

    stored_original = world.events.get(world.incident_id, original["eventId"])
    assert stored_original.detail["value"] == 12
    assert world.events.count(world.incident_id) == 2


def test_correction_target_must_exist(world, factory):
    conflict = only_conflict(
        world.ingest(
            [
                factory.build(
                    et.EVENT_CORRECTED,
                    {"correctsEventId": "00000000-0000-4000-8000-000000000000"},
                    at=5,
                )
            ]
        )
    )
    assert (conflict.code, conflict.reason) == (INVALID_INPUT, "unknown_correction_target")


def test_correction_may_target_an_event_earlier_in_the_same_batch(world, factory):
    original = factory.build(et.ACTION_REPORTED, {"action": "cpr_started"}, at=10)
    correction = factory.build(
        et.EVENT_CORRECTED,
        {"correctsEventId": original["eventId"], "retracted": True, "reason": "mistap"},
        at=11,
    )
    result = world.ingest([original, correction])
    assert len(result.accepted) == 2
    assert not result.conflicts


def test_correction_cannot_target_itself(world, factory):
    payload = factory.build(et.EVENT_CORRECTED, {}, at=5)
    payload["detail"] = {"correctsEventId": payload["eventId"]}
    conflict = only_conflict(world.ingest([payload]))
    assert conflict.reason == "correction_targets_itself"


# -- observations ----------------------------------------------------------


def test_unknown_observation_key_is_rejected(world, factory):
    conflict = only_conflict(
        world.ingest([factory.build(et.OBSERVATION_CONFIRMED, {"key": "patient.mood", "value": "calm"})])
    )
    assert conflict.reason == "unknown_observation_key"


def test_a_model_or_camera_source_cannot_confirm_an_observation(world, factory):
    conflict = only_conflict(
        world.ingest(
            [
                factory.build(
                    et.OBSERVATION_CONFIRMED,
                    {"key": "patient.breathing", "value": True},
                    source="camera_proposal",
                )
            ]
        )
    )
    assert conflict.reason == "source_cannot_confirm"


# -- authorization ---------------------------------------------------------


def test_helper_may_only_submit_its_own_helper_updates(world):
    runner = world.principal_for("runner-uid", ROLE_AED_RUNNER, helper_id="runner-1")
    helper_factory = Factory(namespace="runner", client_id="runner-client", client_instance_id="runner-tab")

    ok = world.ingest(
        [
            helper_factory.build(
                et.HELPER_UPDATED,
                {"helperId": "runner-1", "status": "en_route"},
                at=5,
                source="helper_report",
            )
        ],
        principal=runner,
    )
    assert len(ok.accepted) == 1

    wrong_helper = world.ingest(
        [
            helper_factory.build(
                et.HELPER_UPDATED,
                {"helperId": "runner-2", "status": "en_route"},
                at=6,
                source="helper_report",
            )
        ],
        principal=runner,
    )
    assert only_conflict(wrong_helper).reason == "helper_id_not_owned_by_principal"

    clinical = world.ingest(
        [
            helper_factory.build(
                et.OBSERVATION_CONFIRMED,
                {"key": "patient.breathing", "value": False},
                at=7,
                source="helper_report",
            )
        ],
        principal=runner,
    )
    assert only_conflict(clinical).reason == "helper_may_only_submit_helper_updates"


def test_ems_viewer_cannot_write_any_event(world, factory):
    viewer = world.principal_for("ems-uid", ROLE_EMS_VIEWER)
    with pytest.raises(ServiceError) as excinfo:
        world.ingest([factory.build(et.ACTION_REPORTED, {"action": "cpr_started"})], principal=viewer)
    assert (excinfo.value.code, excinfo.value.reason) == (
        UNAUTHORIZED,
        "role_cannot_write_events",
    )
    assert world.events.count(world.incident_id) == 0


def test_principal_scoped_to_another_incident_is_refused(world, factory):
    from app.services.incident import ROLE_PRIMARY, Principal, ROLE_CAPABILITIES

    foreign = Principal(
        uid="test-primary-uid",
        role=ROLE_PRIMARY,
        incident_id="22222222-3333-4444-8555-666666666666",
        capabilities=ROLE_CAPABILITIES[ROLE_PRIMARY],
    )
    with pytest.raises(ServiceError) as excinfo:
        world.ingest([factory.build(et.ACTION_REPORTED, {"action": "cpr_started"})], principal=foreign)
    assert excinfo.value.reason == "principal_incident_mismatch"


# -- acknowledgement cursor -------------------------------------------------


def test_acknowledged_sequence_stops_at_the_first_gap(world, factory):
    good_one = factory.build(et.ACTION_REPORTED, {"action": "cpr_started"}, at=1)
    rejected = factory.build(et.ACTION_REPORTED, {"action": "x"}, at=2)
    rejected["ruleVersion"] = "demo-v2"
    good_three = factory.build(et.ACTION_REPORTED, {"action": "aed_requested"}, at=3)

    result = world.ingest([good_one, rejected, good_three])

    assert [a.client_sequence for a in result.accepted] == [1, 3]
    # Sequence 2 was rejected, so the cursor stays at 1 and the client
    # re-uploads from 2 rather than assuming 2 was stored.
    assert result.incident.last_acknowledged_client_sequence(PRIMARY_CLIENT_ID) == 1


def test_registration_is_idempotent(world):
    again = world.ingestion.register_incident(
        incident_id=world.incident_id,
        owner_uid="test-primary-uid",
        primary_client_id=PRIMARY_CLIENT_ID,
        rule_version="demo-v1",
    )
    assert again.incident_id == world.incident_id
    assert again.state_revision == 0

    with pytest.raises(ServiceError) as excinfo:
        world.ingestion.register_incident(
            incident_id=world.incident_id,
            owner_uid="someone-else",
            primary_client_id=PRIMARY_CLIENT_ID,
            rule_version="demo-v1",
        )
    assert excinfo.value.reason == "incident_owned_by_another_uid"


@pytest.mark.parametrize(
    ("primary_client_id", "rule_version"),
    [("another-primary-client", "demo-v1"), (PRIMARY_CLIENT_ID, "demo-v2")],
)
def test_registration_replay_must_match_the_original_contract(
    world, primary_client_id, rule_version
):
    with pytest.raises(ServiceError) as excinfo:
        world.ingestion.register_incident(
            incident_id=world.incident_id,
            owner_uid="test-primary-uid",
            primary_client_id=primary_client_id,
            rule_version=rule_version,
        )
    assert excinfo.value.reason == "incident_registration_mismatch"
