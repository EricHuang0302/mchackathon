"""Application-service contract over the shared clinical rule fixtures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.services.rules import (
    ClinicalRuleService,
    ClinicalRulesPort,
    RuleEvaluationFailure,
    RuleEvaluationSuccess,
)
from app.services.rules.cases import SharedCase, load_cases

from .conftest import DEMO_RULE_VERSION

CASES = load_cases()


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


def test_service_implements_the_workstream_port() -> None:
    service: ClinicalRulesPort = ClinicalRuleService()
    outcome = service.evaluate(
        pinned_rule_version=DEMO_RULE_VERSION,
        request=request_for(),
    )
    assert isinstance(outcome, RuleEvaluationSuccess)


def test_success_carries_immutable_package_provenance() -> None:
    service = ClinicalRuleService()
    outcome = service.evaluate(
        pinned_rule_version=DEMO_RULE_VERSION,
        request=request_for(),
    )
    assert isinstance(outcome, RuleEvaluationSuccess)
    assert outcome.pin.rule_version == DEMO_RULE_VERSION
    assert outcome.pin.content_hash.startswith("sha256:")
    assert outcome.pin.review_status == "unreviewed_demo"
    assert outcome.pin.clinical_review_required is True
    assert outcome.decision["reviewStatus"] == "unreviewed_demo"


@pytest.mark.parametrize(
    ("overrides", "code", "detail", "status"),
    [
        ({"expectedStateRevision": 2}, "stale_revision", "state_revision", 409),
        (
            {"modeRevision": 4, "expectedModeRevision": 3},
            "stale_revision",
            "mode_revision",
            409,
        ),
        ({"interactionMode": "speaker_only"}, "invalid_input", "schema_violation", 400),
        ({"observations": "not-a-list"}, "invalid_input", "schema_violation", 400),
    ],
)
def test_expected_domain_errors_are_returned_without_leaking_exceptions(
    overrides: dict[str, Any], code: str, detail: str, status: int
) -> None:
    outcome = ClinicalRuleService().evaluate(
        pinned_rule_version=DEMO_RULE_VERSION,
        request=request_for(**overrides),
    )
    assert isinstance(outcome, RuleEvaluationFailure)
    assert outcome.error.code == code
    assert outcome.error.detail == detail
    assert outcome.error.http_status == status
    assert outcome.error.retryable is False


def test_request_version_must_match_the_incident_pin() -> None:
    outcome = ClinicalRuleService().evaluate(
        pinned_rule_version=DEMO_RULE_VERSION,
        request=request_for(ruleVersion="demo-v0"),
    )
    assert isinstance(outcome, RuleEvaluationFailure)
    assert outcome.error.code == "rule_mismatch"
    assert outcome.error.detail == "incident_rule_version"
    assert outcome.error.http_status == 409


def test_missing_pinned_package_fails_closed() -> None:
    outcome = ClinicalRuleService().evaluate(
        pinned_rule_version="missing-v1",
        request=request_for(ruleVersion="missing-v1"),
    )
    assert isinstance(outcome, RuleEvaluationFailure)
    assert outcome.error.code == "unavailable"
    assert outcome.error.detail == "missing_flow_document"
    assert outcome.error.http_status == 503
    assert outcome.error.retryable is True


def test_loaded_content_stays_pinned_for_the_service_lifetime(
    tmp_path: Path, rules_dir: Path
) -> None:
    copied = tmp_path / "rules"
    copied.mkdir()
    for directory in ("flows", "templates", "schema"):
        source = rules_dir / directory
        target = copied / directory
        target.mkdir()
        for path in source.iterdir():
            if path.is_file():
                (target / path.name).write_bytes(path.read_bytes())

    service = ClinicalRuleService(copied)
    first = service.evaluate(
        pinned_rule_version=DEMO_RULE_VERSION,
        request=request_for(),
    )
    assert isinstance(first, RuleEvaluationSuccess)

    flow_path = copied / "flows" / "demo-v1.flow.yaml"
    flow_path.write_text("invalid: [yaml\n", encoding="utf-8")
    second = service.evaluate(
        pinned_rule_version=DEMO_RULE_VERSION,
        request=request_for(),
    )
    assert isinstance(second, RuleEvaluationSuccess)
    assert second.pin == first.pin
    assert second.decision == first.decision


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.case_id)
def test_service_runs_every_shared_case(case: SharedCase) -> None:
    service = ClinicalRuleService()
    for step in case.steps:
        outcome = service.evaluate(
            pinned_rule_version=case.rule_version,
            request=step["request"],
        )
        expected_error = step.get("expectError")
        if expected_error is not None:
            assert isinstance(outcome, RuleEvaluationFailure), step["stepId"]
            assert outcome.error.code == expected_error["code"], step["stepId"]
            continue

        assert isinstance(outcome, RuleEvaluationSuccess), step["stepId"]
        for field, expected in step["expect"].items():
            assert outcome.decision[field] == expected, (step["stepId"], field)
