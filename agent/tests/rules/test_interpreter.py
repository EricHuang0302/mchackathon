"""Interpreter behavior that the shared cases do not already pin."""

from __future__ import annotations

from typing import Any

import pytest

from app.services.rules import RuleInterpreter
from app.services.rules.errors import (
    InvalidInputError,
    RuleMismatchError,
    StaleRevisionError,
)

from .conftest import DEMO_RULE_VERSION


@pytest.fixture(scope="module")
def interpreter() -> RuleInterpreter:
    return RuleInterpreter.for_version(DEMO_RULE_VERSION)


def request_for(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schemaVersion": "1.0.0",
        "ruleVersion": DEMO_RULE_VERSION,
        "incidentId": "inc-demo-0001",
        "clinicalState": "cpr_in_progress",
        "stateRevision": 3,
        "interactionMode": "voice_guidance",
        "modeRevision": 0,
        "trigger": {"type": "observation"},
        "observations": [],
        "timers": [],
    }
    body.update(overrides)
    return body


def observation(observation_id: str, key: str, value: Any, **overrides: Any) -> dict[str, Any]:
    body = {
        "observationId": observation_id,
        "key": key,
        "value": value,
        "source": "button",
        "observedAt": "2026-09-19T00:00:00.000Z",
        "confirmation": "reported",
    }
    body.update(overrides)
    return body


# --------------------------------------------------------------- determinism


def test_evaluation_is_deterministic(interpreter: RuleInterpreter):
    request = request_for(
        observations=[
            observation("obs-b", "breathing_normal", False),
            observation("obs-a", "ems_arrived", False),
        ]
    )
    first = interpreter.evaluate(request)
    second = interpreter.evaluate(request)
    assert first == second


def test_observation_order_does_not_change_the_decision(interpreter: RuleInterpreter):
    observations = [
        observation("obs-1", "breathing_normal", True),
        observation("obs-2", "ems_arrived", False),
    ]
    forward = interpreter.evaluate(request_for(observations=observations))
    reversed_ = interpreter.evaluate(request_for(observations=list(reversed(observations))))
    assert forward == reversed_
    assert forward["acceptedObservationIds"] == ["obs-1", "obs-2"]


def test_every_decision_carries_the_review_status(interpreter: RuleInterpreter):
    decision = interpreter.evaluate(request_for())
    assert decision["reviewStatus"] == "unreviewed_demo"
    assert decision["interpreterVersion"] == "1.0"
    assert decision["ruleVersion"] == DEMO_RULE_VERSION


# -------------------------------------------------------------------- errors


def test_a_different_rule_version_is_refused(interpreter: RuleInterpreter):
    with pytest.raises(RuleMismatchError) as excinfo:
        interpreter.evaluate(request_for(ruleVersion="demo-v0"))
    assert excinfo.value.code == "rule_mismatch"


def test_a_stale_state_revision_is_refused(interpreter: RuleInterpreter):
    with pytest.raises(StaleRevisionError) as excinfo:
        interpreter.evaluate(request_for(expectedStateRevision=2))
    assert excinfo.value.detail == "state_revision"


def test_a_stale_mode_revision_is_refused(interpreter: RuleInterpreter):
    with pytest.raises(StaleRevisionError) as excinfo:
        interpreter.evaluate(request_for(modeRevision=5, expectedModeRevision=4))
    assert excinfo.value.detail == "mode_revision"


def test_an_undeclared_state_is_invalid_input(interpreter: RuleInterpreter):
    with pytest.raises(InvalidInputError) as excinfo:
        interpreter.evaluate(request_for(clinicalState="aed_analysing"))
    assert excinfo.value.detail == "unknown_state"


def test_an_undeclared_timer_is_invalid_input(interpreter: RuleInterpreter):
    with pytest.raises(InvalidInputError) as excinfo:
        interpreter.evaluate(
            request_for(timers=[{"timerId": "aed_cycle", "status": "running"}])
        )
    assert excinfo.value.detail == "unknown_timer_id"


def test_a_timer_trigger_without_a_timer_id_is_invalid_input(
    interpreter: RuleInterpreter,
):
    with pytest.raises(InvalidInputError) as excinfo:
        interpreter.evaluate(request_for(trigger={"type": "timer"}))
    assert excinfo.value.detail == "missing_timer_id"


def test_a_non_timer_trigger_must_not_name_a_timer(interpreter: RuleInterpreter):
    with pytest.raises(InvalidInputError) as excinfo:
        interpreter.evaluate(
            request_for(trigger={"type": "observation", "timerId": "cpr_reminder"})
        )
    assert excinfo.value.detail == "unexpected_timer_id"


def test_duplicate_observation_ids_are_invalid_input(interpreter: RuleInterpreter):
    with pytest.raises(InvalidInputError) as excinfo:
        interpreter.evaluate(
            request_for(
                observations=[
                    observation("obs-1", "responsive", True),
                    observation("obs-1", "responsive", False),
                ]
            )
        )
    assert excinfo.value.detail == "duplicate_observation_id"


def test_a_malformed_timestamp_is_invalid_input(interpreter: RuleInterpreter):
    with pytest.raises(InvalidInputError) as excinfo:
        interpreter.evaluate(
            request_for(
                observations=[
                    observation("obs-1", "responsive", True, observedAt="2026-09-19T00:00:00Z")
                ]
            )
        )
    assert excinfo.value.detail == "schema_violation"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("observedAt", "2026-13-19T00:00:00.000Z"),
        ("observedAt", "2026-02-30T00:00:00.000Z"),
        ("observedAt", "2026-09-19T25:00:00.000Z"),
        ("receivedAt", "2026-09-31T00:00:00.000Z"),
    ],
)
def test_impossible_utc_timestamp_is_invalid_input(
    interpreter: RuleInterpreter, field: str, value: str
):
    with pytest.raises(InvalidInputError) as excinfo:
        interpreter.evaluate(
            request_for(
                observations=[
                    observation("obs-1", "responsive", True, **{field: value})
                ]
            )
        )
    assert excinfo.value.detail == "invalid_observation_timestamp"


def test_an_unknown_interaction_mode_is_invalid_input(interpreter: RuleInterpreter):
    with pytest.raises(InvalidInputError):
        interpreter.evaluate(request_for(interactionMode="speaker_only"))


# -------------------------------------------------------------- mode policy


def test_dispatcher_guidance_withholds_every_audio_action(interpreter: RuleInterpreter):
    decision = interpreter.evaluate(
        request_for(interactionMode="on_call", modeRevision=2)
    )
    assert decision["outputChannels"] == ["screen"]
    assert all(action["channel"] == "screen" for action in decision["actions"])
    assert {item["kind"] for item in decision["suppressedActions"]} == {
        "metronome_start",
        "speak_template",
    }
    assert decision["instruction"] is not None


def test_handover_suspends_guidance_but_still_records_observations(
    interpreter: RuleInterpreter,
):
    decision = interpreter.evaluate(
        request_for(
            interactionMode="handover",
            observations=[observation("obs-1", "breathing_normal", False)],
        )
    )
    assert decision["guidanceActive"] is False
    assert decision["instruction"] is None
    assert decision["actions"] == []
    assert decision["stateChanged"] is False
    assert decision["acceptedObservationIds"] == ["obs-1"]
    assert decision["resolvedObservations"]["breathing_normal"] is False


def test_a_timer_reminder_never_changes_the_clinical_state(
    interpreter: RuleInterpreter,
):
    decision = interpreter.evaluate(
        request_for(
            trigger={"type": "timer", "timerId": "cpr_reminder"},
            timers=[{"timerId": "cpr_reminder", "status": "running"}],
        )
    )
    assert decision["toState"] == decision["fromState"] == "cpr_in_progress"
    assert decision["stateChanged"] is False
    assert decision["nextStateRevision"] == decision["stateRevision"]


def test_resume_emits_one_operation_per_paused_timer_and_no_reminder(
    interpreter: RuleInterpreter,
):
    decision = interpreter.evaluate(
        request_for(
            trigger={"type": "resume"},
            timers=[
                {"timerId": "cpr_reminder", "status": "paused"},
                {"timerId": "reassess_breathing", "status": "stopped"},
            ],
        )
    )
    assert [op["op"] for op in decision["timerOps"]] == ["resume"]
    assert decision["timerOps"][0]["timerId"] == "cpr_reminder"
    assert decision["instruction"]["templateId"] == "cpr.continue"
    assert [notice["templateId"] for notice in decision["notices"]] == [
        "resume.interruption"
    ]


def test_timer_operations_follow_package_declaration_order(
    interpreter: RuleInterpreter,
):
    decision = interpreter.evaluate(
        request_for(
            clinicalState="assess_breathing",
            stateRevision=2,
            observations=[
                observation("obs-1", "responsive", False),
                observation("obs-2", "breathing_normal", True),
            ],
        )
    )
    assert [op["timerId"] for op in decision["timerOps"]] == [
        "cpr_reminder",
        "reassess_breathing",
    ]


# ------------------------------------------------------------- unknown inputs


def test_an_unknown_observation_never_becomes_false(interpreter: RuleInterpreter):
    decision = interpreter.evaluate(request_for(clinicalState="assess_responsiveness"))
    assert decision["resolvedObservations"]["responsive"] == "unknown"
    assert "responsive" in decision["unknownObservationKeys"]
    assert decision["stateChanged"] is False


def test_the_catalog_bounds_the_resolved_keys(interpreter: RuleInterpreter):
    decision = interpreter.evaluate(
        request_for(observations=[observation("obs-1", "patient_name", "x")])
    )
    assert "patient_name" not in decision["resolvedObservations"]
    assert decision["rejectedObservations"] == [
        {
            "observationId": "obs-1",
            "key": "patient_name",
            "code": "unknown_observation_key",
        }
    ]
