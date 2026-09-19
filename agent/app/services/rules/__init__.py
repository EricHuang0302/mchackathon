"""Python interpreter for the shared clinical rule packages in ``rules/``.

Workstream 5 owns this package. It loads versioned restricted-YAML rule
packages, validates them against the JSON Schemas in ``rules/schema/``, and
evaluates observations deterministically so the TypeScript interpreter in
``web/src/lib/rules/`` can reproduce the same decision from the same request.

Nothing here performs an external effect. A decision carries approved template
references, action intents, timer operations, and the revisions a caller must
still check before acting.
"""

from .conditions import ALLOWED_OPERATORS, Tri, UNKNOWN
from .contract import (
    ClinicalRulesPort,
    RuleEvaluationFailure,
    RuleEvaluationOutcome,
    RuleEvaluationSuccess,
    RulePackagePin,
    RuleServiceError,
    RuleServiceErrorCode,
)
from .errors import (
    InvalidInputError,
    RestrictedYamlError,
    RuleError,
    RuleMismatchError,
    RulePackageError,
    StaleRevisionError,
)
from .interpreter import DECISION_SCHEMA_VERSION, RuleInterpreter
from .package import (
    INTERPRETER_VERSION,
    RulePackage,
    compute_content_hash,
    load_package,
    load_package_from_text,
)
from .observations import ResolvedObservations, UNKNOWN_VALUE, resolve
from .restricted_yaml import load_restricted_yaml
from .service import ClinicalRuleService

__all__ = [
    "ALLOWED_OPERATORS",
    "ClinicalRuleService",
    "ClinicalRulesPort",
    "DECISION_SCHEMA_VERSION",
    "INTERPRETER_VERSION",
    "InvalidInputError",
    "ResolvedObservations",
    "RestrictedYamlError",
    "RuleError",
    "RuleEvaluationFailure",
    "RuleEvaluationOutcome",
    "RuleEvaluationSuccess",
    "RuleInterpreter",
    "RuleMismatchError",
    "RulePackage",
    "RulePackagePin",
    "RulePackageError",
    "StaleRevisionError",
    "RuleServiceError",
    "RuleServiceErrorCode",
    "Tri",
    "UNKNOWN",
    "UNKNOWN_VALUE",
    "compute_content_hash",
    "load_package",
    "load_package_from_text",
    "load_restricted_yaml",
    "resolve",
]
