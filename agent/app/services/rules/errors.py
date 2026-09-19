"""Error types raised by the clinical rule interpreter.

The three request-level codes (``rule_mismatch``, ``stale_revision``,
``invalid_input``) match the error vocabulary in ``docs/sdd.md`` and the
``expectError.code`` enum of ``rules/schema/case.v1.schema.json``. Rule package
problems are a separate, load-time concern and carry a finer-grained ``detail``
so validation tests can assert exactly which rule was violated.
"""

from __future__ import annotations


class RuleError(Exception):
    """Base class for every error the rules subsystem raises."""

    code = "rule_error"

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def __str__(self) -> str:  # pragma: no cover - trivial
        if self.detail:
            return f"[{self.code}/{self.detail}] {self.message}"
        return f"[{self.code}] {self.message}"


class RulePackageError(RuleError):
    """A rule package could not be loaded or failed validation."""

    code = "invalid_rule_package"


class RestrictedYamlError(RulePackageError):
    """A document used YAML features outside the supported restricted subset."""

    code = "restricted_yaml"


class RuleMismatchError(RuleError):
    """The pinned rule version or interpreter version is not usable here."""

    code = "rule_mismatch"


class StaleRevisionError(RuleError):
    """An expected state or mode revision did not match the current one."""

    code = "stale_revision"


class InvalidInputError(RuleError):
    """The evaluation request itself is malformed."""

    code = "invalid_input"
