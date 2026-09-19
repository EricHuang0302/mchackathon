"""Stable service contract for pinned clinical-rule evaluation.

The transport layer owns authentication, incident lookup, and serialization.
This module keeps those concerns out of the rule engine while giving callers a
typed success/error boundary that does not expose interpreter exceptions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Protocol, TypeAlias

RuleServiceErrorCode: TypeAlias = Literal[
    "invalid_input", "stale_revision", "rule_mismatch", "unavailable"
]


@dataclass(frozen=True, slots=True)
class RulePackagePin:
    """Immutable provenance for the package used by one evaluation."""

    rule_version: str
    content_hash: str
    review_status: Literal["unreviewed_demo", "in_review", "reviewed"]
    clinical_review_required: bool


@dataclass(frozen=True, slots=True)
class RuleServiceError:
    """Transport-neutral failure with an API-compatible public code."""

    code: RuleServiceErrorCode
    message: str
    detail: str | None
    http_status: int
    retryable: bool


@dataclass(frozen=True, slots=True)
class RuleEvaluationSuccess:
    pin: RulePackagePin
    decision: Mapping[str, Any]
    ok: Literal[True] = field(default=True, init=False)


@dataclass(frozen=True, slots=True)
class RuleEvaluationFailure:
    error: RuleServiceError
    ok: Literal[False] = field(default=False, init=False)


RuleEvaluationOutcome: TypeAlias = RuleEvaluationSuccess | RuleEvaluationFailure


class ClinicalRulesPort(Protocol):
    """Workstream 1 boundary for evaluating an incident-pinned rule version."""

    def evaluate(
        self,
        *,
        pinned_rule_version: str,
        request: Mapping[str, Any],
    ) -> RuleEvaluationOutcome: ...
