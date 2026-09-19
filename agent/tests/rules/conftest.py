"""Fixtures for the clinical rule interpreter tests.

Validation tests mutate a parsed copy of the real demo package rather than
maintaining a second inline package, so a change to the shared package keeps the
negative tests honest instead of letting them drift.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable

import pytest

from app.services.rules import package as package_module
from app.services.rules.restricted_yaml import load_restricted_yaml
from app.services.rules.schemas import default_rules_dir

DEMO_RULE_VERSION = "demo-v1"


@pytest.fixture(scope="session")
def rules_dir() -> Path:
    return default_rules_dir()


@pytest.fixture(scope="session")
def flow_text(rules_dir: Path) -> str:
    return (rules_dir / "flows" / f"{DEMO_RULE_VERSION}.flow.yaml").read_text(
        encoding="utf-8"
    )


@pytest.fixture(scope="session")
def templates_text(rules_dir: Path) -> str:
    return (
        rules_dir / "templates" / f"{DEMO_RULE_VERSION}.zh-TW.templates.yaml"
    ).read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def _parsed_flow(flow_text: str) -> dict[str, Any]:
    return load_restricted_yaml(flow_text, source="demo flow")


@pytest.fixture(scope="session")
def _parsed_templates(templates_text: str) -> dict[str, Any]:
    return load_restricted_yaml(templates_text, source="demo templates")


@pytest.fixture
def flow(_parsed_flow: dict[str, Any]) -> dict[str, Any]:
    """A fresh, mutable copy of the demo flow document."""
    return copy.deepcopy(_parsed_flow)


@pytest.fixture
def templates(_parsed_templates: dict[str, Any]) -> dict[str, Any]:
    """A fresh, mutable copy of the demo template document."""
    return copy.deepcopy(_parsed_templates)


@pytest.fixture
def build(
    flow: dict[str, Any], templates: dict[str, Any]
) -> Callable[..., package_module.RulePackage]:
    """Build a package from the demo documents, optionally overridden."""

    def _build(
        flow_document: dict[str, Any] | None = None,
        templates_document: dict[str, Any] | None = None,
    ) -> package_module.RulePackage:
        return package_module.build_package(
            flow_document if flow_document is not None else flow,
            templates_document if templates_document is not None else templates,
            flow_source="demo flow",
            templates_source="demo templates",
            content_hash="sha256:test",
        )

    return _build


def state_of(flow_document: dict[str, Any], state_id: str) -> dict[str, Any]:
    for state in flow_document["states"]:
        if state["id"] == state_id:
            return state
    raise AssertionError(f"state {state_id!r} is missing from the fixture")
