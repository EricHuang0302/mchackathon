"""Application-facing facade for deterministic clinical-rule evaluation."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any, Mapping

from .contract import (
    RuleEvaluationFailure,
    RuleEvaluationOutcome,
    RuleEvaluationSuccess,
    RulePackagePin,
    RuleServiceError,
)
from .errors import (
    InvalidInputError,
    RuleError,
    RuleMismatchError,
    RulePackageError,
    StaleRevisionError,
)
from .interpreter import RuleInterpreter

_ERROR_HTTP_STATUS = {
    "invalid_input": 400,
    "stale_revision": 409,
    "rule_mismatch": 409,
    "unavailable": 503,
}


class ClinicalRuleService:
    """Load and retain rule packages by incident-pinned version.

    Successful package loads are cached for the lifetime of this service. A
    running incident therefore cannot silently switch to modified rule content
    under the same ``ruleVersion``. Deploy a new version identifier for changed
    rule content.
    """

    def __init__(self, rules_dir: Path | str | None = None) -> None:
        self._rules_dir = Path(rules_dir) if rules_dir is not None else None
        self._interpreters: dict[str, RuleInterpreter] = {}
        self._lock = RLock()

    def evaluate(
        self,
        *,
        pinned_rule_version: str,
        request: Mapping[str, Any],
    ) -> RuleEvaluationOutcome:
        """Evaluate input against exactly the incident-pinned package.

        No exception from the expected rules-domain vocabulary crosses this
        boundary. The caller can map the returned public code and HTTP status
        directly while retaining ``detail`` for diagnostics.
        """
        request_rule_version = request.get("ruleVersion")
        if (
            isinstance(request_rule_version, str)
            and request_rule_version != pinned_rule_version
        ):
            return self._failure(
                RuleMismatchError(
                    f"request pins rule version {request_rule_version!r} but the "
                    f"incident pins {pinned_rule_version!r}",
                    detail="incident_rule_version",
                )
            )

        try:
            interpreter = self._interpreter_for(pinned_rule_version)
            decision = interpreter.evaluate(request)
        except RulePackageError as exc:
            return self._unavailable(exc)
        except RuleError as exc:
            return self._failure(exc)

        package = interpreter.package
        return RuleEvaluationSuccess(
            pin=RulePackagePin(
                rule_version=package.rule_version,
                content_hash=package.content_hash,
                review_status=package.review_status,
                clinical_review_required=package.clinical_review_required,
            ),
            decision=decision,
        )

    def _interpreter_for(self, rule_version: str) -> RuleInterpreter:
        with self._lock:
            interpreter = self._interpreters.get(rule_version)
            if interpreter is None:
                interpreter = RuleInterpreter.for_version(
                    rule_version, rules_dir=self._rules_dir
                )
                self._interpreters[rule_version] = interpreter
            return interpreter

    @staticmethod
    def _failure(exc: RuleError) -> RuleEvaluationFailure:
        if isinstance(exc, InvalidInputError):
            code = "invalid_input"
        elif isinstance(exc, StaleRevisionError):
            code = "stale_revision"
        elif isinstance(exc, RuleMismatchError):
            code = "rule_mismatch"
        else:  # pragma: no cover - all request errors are classified above
            code = "unavailable"
        return RuleEvaluationFailure(
            error=RuleServiceError(
                code=code,
                message=exc.message,
                detail=exc.detail,
                http_status=_ERROR_HTTP_STATUS[code],
                retryable=code == "unavailable",
            )
        )

    @staticmethod
    def _unavailable(exc: RulePackageError) -> RuleEvaluationFailure:
        return RuleEvaluationFailure(
            error=RuleServiceError(
                code="unavailable",
                message="The pinned rule package is unavailable",
                detail=exc.detail,
                http_status=_ERROR_HTTP_STATUS["unavailable"],
                retryable=True,
            )
        )
