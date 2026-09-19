"""Loading and execution of the shared interpreter cases in ``rules/cases/``.

The cases are the parity contract between this interpreter and the TypeScript
one in ``web/src/lib/rules/``. This module keeps the Python side of that contract
in one place so the pytest suite and any future service check run cases exactly
the way the case schema describes them.

``index.json`` lists the case files. It is checked against the directory
contents on load, so adding a case file without listing it, or listing one that
does not exist, fails loudly instead of silently reducing coverage.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .errors import RuleError, RulePackageError
from .interpreter import RuleInterpreter
from .schemas import CASE_SCHEMA, default_rules_dir, validate_against_schema

CASE_SUFFIX = ".case.json"
INDEX_FILE = "index.json"


@dataclass(frozen=True)
class SharedCase:
    case_id: str
    title: str
    description: str
    rule_version: str
    steps: tuple[Mapping[str, Any], ...]
    path: Path


def cases_dir(rules_dir: Path | str | None = None) -> Path:
    base = Path(rules_dir) if rules_dir is not None else default_rules_dir()
    return base / "cases"


def load_cases(rules_dir: Path | str | None = None) -> list[SharedCase]:
    """Load every listed case, validating the index and each document."""
    directory = cases_dir(rules_dir)
    index_path = directory / INDEX_FILE
    if not index_path.is_file():
        raise RulePackageError(
            f"missing case index at {index_path}", detail="missing_case_index"
        )
    index = json.loads(index_path.read_text(encoding="utf-8"))
    listed = list(index["cases"])
    on_disk = sorted(path.name for path in directory.glob(f"*{CASE_SUFFIX}"))
    if sorted(listed) != on_disk:
        raise RulePackageError(
            f"{INDEX_FILE} lists {sorted(listed)} but the directory holds {on_disk}",
            detail="case_index_mismatch",
        )

    cases: list[SharedCase] = []
    for name in listed:
        path = directory / name
        document = json.loads(path.read_text(encoding="utf-8"))
        validate_against_schema(document, CASE_SCHEMA, source=name)
        expected_id = name[: -len(CASE_SUFFIX)]
        if document["caseId"] != expected_id:
            raise RulePackageError(
                f"{name}: caseId {document['caseId']!r} does not match the file name",
                detail="case_id_mismatch",
            )
        cases.append(
            SharedCase(
                case_id=document["caseId"],
                title=document["title"],
                description=document["description"],
                rule_version=document["ruleVersion"],
                steps=tuple(document["steps"]),
                path=path,
            )
        )
    return cases


@dataclass(frozen=True)
class StepFailure:
    step_id: str
    field: str
    expected: Any
    actual: Any

    def describe(self) -> str:
        return (
            f"step {self.step_id!r} field {self.field!r}\n"
            f"  expected: {json.dumps(self.expected, ensure_ascii=False, sort_keys=True)}\n"
            f"  actual:   {json.dumps(self.actual, ensure_ascii=False, sort_keys=True)}"
        )


def run_step(
    interpreter: RuleInterpreter, step: Mapping[str, Any]
) -> list[StepFailure]:
    """Run one case step and return the mismatches it produced."""
    step_id = step["stepId"]
    expect_error = step.get("expectError")
    try:
        decision = interpreter.evaluate(step["request"])
    except RuleError as exc:
        if expect_error is None:
            return [
                StepFailure(step_id, "<error>", step.get("expect"), {"code": exc.code})
            ]
        if exc.code != expect_error["code"]:
            return [
                StepFailure(step_id, "<error>.code", expect_error["code"], exc.code)
            ]
        return []

    if expect_error is not None:
        return [StepFailure(step_id, "<error>.code", expect_error["code"], None)]

    failures: list[StepFailure] = []
    for field, expected in step["expect"].items():
        if field not in decision:
            failures.append(StepFailure(step_id, field, expected, None))
            continue
        actual = decision[field]
        if actual != expected:
            failures.append(StepFailure(step_id, field, expected, actual))
    return failures


def run_case(case: SharedCase, rules_dir: Path | str | None = None) -> list[StepFailure]:
    """Run every step of a case against its pinned package."""
    interpreter = RuleInterpreter.for_version(case.rule_version, rules_dir)
    failures: list[StepFailure] = []
    for step in case.steps:
        failures.extend(run_step(interpreter, step))
    return failures
