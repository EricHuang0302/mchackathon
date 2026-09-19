"""Every shared case in rules/cases/ runs against the Python interpreter.

The TypeScript interpreter in web/src/lib/rules/ runs the same files. Cases are
enumerated from rules/cases/index.json, and loading checks that index against
the directory contents, so a new case file cannot be added without being run.
"""

from __future__ import annotations

import pytest

from app.services.rules.cases import SharedCase, load_cases, run_case

CASES = load_cases()
CASE_IDS = [case.case_id for case in CASES]

REQUIRED_COVERAGE = {
    "assessment-to-cpr",
    "bleeding-control",
    "call-mode-interruption",
    "conflicting-observations",
    "recovery-position",
    "resume-after-interruption",
    "scope-and-transition-order",
    "stale-revisions-and-mismatches",
    "timer-changes",
    "unknown-observations",
}


def test_the_index_covers_the_agreed_scenarios():
    assert REQUIRED_COVERAGE <= set(CASE_IDS)


def test_case_ids_are_unique():
    assert len(CASE_IDS) == len(set(CASE_IDS))


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_shared_case(case: SharedCase):
    failures = run_case(case)
    if failures:
        report = "\n".join(failure.describe() for failure in failures)
        pytest.fail(f"{case.case_id} ({case.path.name}):\n{report}", pytrace=False)


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_every_step_asserts_something(case: SharedCase):
    for step in case.steps:
        assert step.get("expect") or step.get("expectError"), step["stepId"]
