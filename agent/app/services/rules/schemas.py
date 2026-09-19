"""Access to the shared JSON Schemas in ``rules/schema/``.

The schema files are the cross-runtime contract: Python validates against the
same documents the TypeScript interpreter and the shared cases refer to.
"""

from __future__ import annotations

import functools
import json
import os
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource

from .errors import RulePackageError

SUPPORTED_SCHEMA_VERSION = "1.0.0"

RULE_PACKAGE_SCHEMA = "rule-package.v1.schema.json"
RULE_TEMPLATES_SCHEMA = "rule-templates.v1.schema.json"
OBSERVATION_SCHEMA = "observation.v1.schema.json"
EVALUATION_REQUEST_SCHEMA = "evaluation-request.v1.schema.json"
DECISION_SCHEMA = "decision.v1.schema.json"
CASE_SCHEMA = "case.v1.schema.json"

_RULES_DIR_ENV = "FIRST_AID_RULES_DIR"
_REPO_RULES_DIR = Path(__file__).resolve().parents[4] / "rules"


def default_rules_dir() -> Path:
    """Locate ``rules/``; the environment variable wins when it is set."""
    override = os.environ.get(_RULES_DIR_ENV)
    if override:
        return Path(override)
    return _REPO_RULES_DIR


def schema_dir() -> Path:
    return default_rules_dir() / "schema"


@functools.lru_cache(maxsize=None)
def _load_schemas(directory: str) -> tuple[dict[str, Any], Registry]:
    schemas: dict[str, Any] = {}
    resources: list[tuple[str, Resource]] = []
    for path in sorted(Path(directory).glob("*.schema.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        schemas[path.name] = document
        resources.append((document["$id"], Resource.from_contents(document)))
    if not schemas:
        raise RulePackageError(
            f"no JSON Schemas found in {directory}", detail="missing_schemas"
        )
    return schemas, Registry().with_resources(resources)


def get_schema(name: str) -> dict[str, Any]:
    schemas, _ = _load_schemas(str(schema_dir()))
    try:
        return schemas[name]
    except KeyError as exc:  # pragma: no cover - configuration error
        raise RulePackageError(
            f"schema {name} not found in {schema_dir()}", detail="missing_schemas"
        ) from exc


def validate_against_schema(
    instance: Any,
    schema_name: str,
    *,
    source: str,
    error_type: type[Exception] = RulePackageError,
    detail: str = "schema_violation",
) -> None:
    """Validate ``instance`` and raise ``error_type`` on the first failure.

    Errors are reported in a stable order (``best_match`` over sorted errors) so
    the same malformed document always produces the same message.
    """
    _, registry = _load_schemas(str(schema_dir()))
    validator = jsonschema.Draft202012Validator(
        get_schema(schema_name), registry=registry
    )
    errors = sorted(validator.iter_errors(instance), key=jsonschema.exceptions.relevance)
    if not errors:
        return
    error = errors[0]
    location = "/".join(str(part) for part in error.absolute_path)
    raise error_type(
        f"{source}: {schema_name} violation at /{location}: {error.message}",
        detail=detail,
    )
