"""The synthetic ``eval/`` scenarios must stay deterministic and truthful."""

from __future__ import annotations

import json

import pytest

from eval.run_scenarios import run_all
from eval.scenarios import SCENARIOS, SCENARIOS_BY_NAME


@pytest.mark.parametrize("name", sorted(SCENARIOS_BY_NAME))
def test_a_scenario_produces_identical_output_on_every_run(name: str) -> None:
    module = SCENARIOS_BY_NAME[name]
    first = json.dumps(module.run(), sort_keys=True, default=str)
    second = json.dumps(module.run(), sort_keys=True, default=str)
    assert first == second


def test_every_scenario_module_declares_its_interface() -> None:
    for module in SCENARIOS:
        assert isinstance(module.NAME, str) and module.NAME
        assert isinstance(module.DESCRIPTION, str) and module.DESCRIPTION
        assert callable(module.run)


def test_run_all_covers_every_scenario() -> None:
    assert set(run_all()) == set(SCENARIOS_BY_NAME)


# -- call switching ---------------------------------------------------------


def test_call_switching_preserves_history_and_rejects_a_replayed_mode() -> None:
    result = SCENARIOS_BY_NAME["call_switching"].run()

    assert result["finalInteractionMode"] == "handover"
    assert result["finalModeRevision"] == 4
    assert result["finalStatus"] == "handed_over"
    # A call report is a user statement; it does not move the mode by itself.
    assert result["modeAfterCallEndReport"] == "on_call"
    assert [c["reason"] for c in result["staleModeConflicts"]] == [
        "mode_revision_not_advancing"
    ]
    # Treatment history survives every mode switch.
    assert result["actionsPreserved"] == ["cpr_started", "ems_arrived"]

    revisions = [step["modeRevision"] for step in result["steps"]]
    assert revisions == sorted(revisions)


# -- offline recovery -------------------------------------------------------


def test_offline_recovery_deduplicates_and_preserves_the_local_mode() -> None:
    result = SCENARIOS_BY_NAME["offline_recovery"].run()

    assert result["retryAddedEvents"] == 0
    assert {a["status"] for a in result["retryAcknowledgements"]} == {"duplicate"}
    # The interrupted upload stops at the last contiguous acknowledgement.
    assert result["resumeAfterInterruption"] == 5
    assert [c["reason"] for c in result["staleModeConflicts"]] == [
        "mode_revision_not_advancing"
    ]

    reconcile = result["reconcile"]
    assert reconcile["modePreserved"] is True
    assert reconcile["interactionMode"] == "on_call"
    assert reconcile["modeRevision"] == 2
    assert reconcile["authorityEpoch"] == 1
    assert reconcile["replayExecutionAllowed"] is False
    assert reconcile["catchUpComplete"] is True
    assert "server_mode_revision_behind_client" in [
        c["reason"] for c in reconcile["conflicts"]
    ]


def test_offline_recovery_projects_out_of_order_uploads_correctly() -> None:
    result = SCENARIOS_BY_NAME["offline_recovery"].run()
    assert result["snapshotMatchesInOrderProjection"] is True
    assert {a["status"] for a in result["outOfOrderAcknowledgements"]} == {"accepted"}


# -- snapshot-first handoff -------------------------------------------------


def test_handoff_protects_confirmed_facts_from_later_proposals() -> None:
    result = SCENARIOS_BY_NAME["snapshot_first_handoff"].run()

    breathing = result["confirmedBreathing"]
    assert breathing["value"] is False
    assert breathing["confirmation"] == "confirmed"
    assert breathing["pendingProposalValues"] == [True]

    # A camera proposal for an unheld field is shown as a proposal, not a fact.
    assert result["cameraProposedHazard"]["confirmation"] == "proposed"


def test_handoff_keeps_unknown_fields_unknown() -> None:
    result = SCENARIOS_BY_NAME["snapshot_first_handoff"].run()

    unreported = result["unreportedField"]
    assert unreported["value"] is None
    assert unreported["confirmation"] == "unknown"
    assert unreported["evidenceEventIds"] == []
    assert result["mist"]["unknownInjuryKeys"] == [
        "patient.injuries",
        "patient.chiefComplaint",
        "patient.bleeding",
    ]


def test_handoff_keeps_the_four_treatment_claims_distinct() -> None:
    mist = SCENARIOS_BY_NAME["snapshot_first_handoff"].run()["mist"]
    assert mist["reportedActions"] == ["cpr_started"]
    assert mist["recommendedActionCount"] == 1
    assert mist["issuedCommandCount"] == 1
    assert mist["deviceAcknowledgementCount"] == 1


def test_handoff_shows_a_correction_next_to_its_original() -> None:
    result = SCENARIOS_BY_NAME["snapshot_first_handoff"].run()

    assert result["correctedBystanderCount"]["value"] == 2
    assert result["correctedBystanderCount"]["confirmation"] == "confirmed"
    pairing = result["originalAndCorrectionBothPresent"]
    assert pairing["correctionCount"] == 1
    assert pairing["originalsStillPresent"] == 1


def test_handoff_denies_the_timeline_to_greeter_and_runner() -> None:
    result = SCENARIOS_BY_NAME["snapshot_first_handoff"].run()

    assert result["greeterTimeline"] == {
        "denied": True,
        "code": "unauthorized",
        "reason": "capability_denied",
    }
    assert result["runnerTimeline"]["denied"] is True
    assert result["runnerMist"]["denied"] is True
    assert result["greeterCanReadSnapshot"] is True
    assert result["runnerCanReadSnapshot"] is False


def test_handoff_pages_are_bounded_and_sanitized() -> None:
    result = SCENARIOS_BY_NAME["snapshot_first_handoff"].run()

    pages = result["timelinePages"]
    assert all(page["entryCount"] <= 5 for page in pages)
    assert pages[-1]["hasMore"] is False
    assert pages[-1]["nextCursor"] is None

    # The EMS view of a decision drops fields the primary keeps.
    assert set(result["emsDetailKeysForDecision"]) < set(
        result["primaryDetailKeysForDecision"]
    )
    # A helper row carries task progress only, never a location.
    for row in result["sanitizedHelperRows"]:
        assert set(row) == {"helperId", "role", "status"}


def test_the_aed_failure_appears_only_as_an_input_event() -> None:
    """Reassignment is the AED service's job and is not simulated here."""
    result = SCENARIOS_BY_NAME["snapshot_first_handoff"].run()
    statuses = [row["status"] for row in result["sanitizedHelperRows"]]
    assert statuses == ["unavailable"]
    assert "reassignment" not in json.dumps(result)
    assert "targetAedId" not in json.dumps(result)
