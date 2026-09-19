"""Rule package validation: every documented rejection has a test."""

from __future__ import annotations

import copy
import json
from typing import Any, Callable

import pytest

from app.services.rules import load_package, load_package_from_text
from app.services.rules.errors import RuleMismatchError, RulePackageError
from app.services.rules.package import INTERPRETER_VERSION, compute_content_hash

from .conftest import DEMO_RULE_VERSION, state_of

Build = Callable[..., Any]


def rejects(build: Build, flow: dict[str, Any], detail: str) -> None:
    with pytest.raises(RulePackageError) as excinfo:
        build(flow)
    assert excinfo.value.detail == detail, excinfo.value.message


# ------------------------------------------------------------- the real package


def test_demo_package_loads_and_is_marked_unreviewed():
    package = load_package(DEMO_RULE_VERSION)
    assert package.rule_version == DEMO_RULE_VERSION
    assert package.review_status == "unreviewed_demo"
    assert package.clinical_review_required is True
    assert package.locale == "zh-TW"
    assert INTERPRETER_VERSION in package.compatible_interpreter_versions
    assert package.content_hash.startswith("sha256:")


def test_demo_package_declares_no_aed_content():
    """AED handling belongs to another workstream and is deliberately absent."""
    package = load_package(DEMO_RULE_VERSION)
    assert not any("aed" in key for key in package.observations)
    assert not any("aed" in state_id for state_id in package.states)


def test_content_hash_ignores_line_endings_and_bom(flow_text: str, templates_text: str):
    crlf = compute_content_hash(
        [
            ("flow", "﻿" + flow_text.replace("\n", "\r\n")),
            ("templates", templates_text.replace("\n", "\r\n")),
        ]
    )
    lf = compute_content_hash([("flow", flow_text), ("templates", templates_text)])
    assert crlf == lf


def test_content_hash_changes_with_content(flow_text: str, templates_text: str):
    original = compute_content_hash([("flow", flow_text), ("templates", templates_text)])
    edited = compute_content_hash(
        [("flow", flow_text), ("templates", templates_text + "\n# trailing\n")]
    )
    assert original != edited


def test_load_package_from_text_round_trips(flow_text: str, templates_text: str):
    package = load_package_from_text(flow_text, templates_text)
    assert package.rule_version == DEMO_RULE_VERSION


# ------------------------------------------------------------------- manifest


def test_unsupported_schema_version_is_rejected(build: Build, flow: dict[str, Any]):
    flow["schemaVersion"] = "2.0.0"
    with pytest.raises(RulePackageError) as excinfo:
        build(flow)
    assert excinfo.value.detail in ("unsupported_schema_version", "schema_violation")


def test_incompatible_interpreter_version_is_a_rule_mismatch(
    build: Build, flow: dict[str, Any]
):
    flow["compatibleInterpreterVersions"] = ["9.9"]
    with pytest.raises(RuleMismatchError) as excinfo:
        build(flow)
    assert excinfo.value.detail == "interpreter_incompatible"


def test_templates_manifest_must_match_the_flow(
    build: Build, flow: dict[str, Any], templates: dict[str, Any]
):
    templates["ruleVersion"] = "demo-v2"
    with pytest.raises(RulePackageError) as excinfo:
        build(flow, templates)
    assert excinfo.value.detail == "templates_manifest_mismatch"


def test_unknown_initial_state_is_rejected(build: Build, flow: dict[str, Any]):
    flow["initialState"] = "not_a_state"
    rejects(build, flow, "unknown_initial_state")


def test_unknown_field_is_rejected_by_the_schema(build: Build, flow: dict[str, Any]):
    flow["unexpectedField"] = "x"
    rejects(build, flow, "schema_violation")


# ------------------------------------------------------------------ structure


def test_duplicate_state_id_is_rejected(build: Build, flow: dict[str, Any]):
    flow["states"].append(copy.deepcopy(state_of(flow, "scene_unsafe")))
    rejects(build, flow, "duplicate_state_id")


def test_duplicate_transition_id_is_rejected(build: Build, flow: dict[str, Any]):
    state = state_of(flow, "assess_responsiveness")
    state["transitions"][1]["id"] = state["transitions"][0]["id"]
    rejects(build, flow, "duplicate_transition_id")


def test_duplicate_observation_key_is_rejected(build: Build, flow: dict[str, Any]):
    flow["observations"].append(copy.deepcopy(flow["observations"][0]))
    rejects(build, flow, "duplicate_observation_key")


def test_duplicate_timer_id_is_rejected(build: Build, flow: dict[str, Any]):
    flow["timers"].append(copy.deepcopy(flow["timers"][0]))
    rejects(build, flow, "duplicate_timer_id")


def test_duplicate_template_id_is_rejected(
    build: Build, flow: dict[str, Any], templates: dict[str, Any]
):
    templates["templates"].append(copy.deepcopy(templates["templates"][0]))
    with pytest.raises(RulePackageError) as excinfo:
        build(flow, templates)
    assert excinfo.value.detail == "duplicate_template_id"


def test_dangling_transition_target_is_rejected(build: Build, flow: dict[str, Any]):
    state_of(flow, "assess_responsiveness")["transitions"][0]["to"] = "nowhere"
    rejects(build, flow, "dangling_transition_target")


def test_guidance_state_without_transitions_is_rejected(
    build: Build, flow: dict[str, Any]
):
    state = state_of(flow, "scene_unsafe")
    state["transitions"] = []
    rejects(build, flow, "guidance_state_has_no_transitions")


def test_terminal_state_with_transitions_is_rejected(build: Build, flow: dict[str, Any]):
    terminal = state_of(flow, "handover_to_ems")
    terminal["transitions"] = [
        {
            "id": "t_back",
            "when": {"eq": {"key": "ems_arrived", "value": False}},
            "to": "cpr_in_progress",
            "reasonCode": "impossible",
        }
    ]
    terminal["requiredObservations"] = ["ems_arrived"]
    rejects(build, flow, "terminal_state_has_transitions")


# ----------------------------------------------------------------- conditions


def test_unknown_operator_is_rejected(build: Build, flow: dict[str, Any]):
    state_of(flow, "assess_responsiveness")["transitions"][0]["when"] = {
        "matches": {"key": "responsive", "value": "^yes$"}
    }
    rejects(build, flow, "schema_violation")


def test_unimplemented_ne_operator_is_not_advertised_by_the_schema(
    build: Build, flow: dict[str, Any]
):
    state_of(flow, "assess_responsiveness")["transitions"][0]["when"] = {
        "ne": {"key": "responsive", "value": True}
    }
    rejects(build, flow, "schema_violation")


def test_unknown_operator_is_rejected_by_the_evaluator_too():
    """A condition reaching the evaluator with an unknown operator still fails."""
    from app.services.rules import conditions

    with pytest.raises(RulePackageError) as excinfo:
        conditions.evaluate({"matches": {"key": "responsive"}}, {})
    assert excinfo.value.detail == "unknown_operator"


def test_condition_on_a_key_outside_the_catalog_is_rejected(
    build: Build, flow: dict[str, Any]
):
    state = state_of(flow, "assess_responsiveness")
    state["transitions"][0]["when"] = {"eq": {"key": "pupils_equal", "value": True}}
    state["requiredObservations"] = ["pupils_equal", "responsive"]
    rejects(build, flow, "unknown_observation_key")


def test_numeric_operator_on_a_non_numeric_key_is_rejected(
    build: Build, flow: dict[str, Any]
):
    state = state_of(flow, "assess_responsiveness")
    state["transitions"][0]["when"] = {"lt": {"key": "responsive", "value": 1}}
    rejects(build, flow, "invalid_condition_value")


def test_comparison_value_outside_an_enum_is_rejected(build: Build, flow: dict[str, Any]):
    state = state_of(flow, "responsive_patient")
    state["transitions"][2]["when"] = {
        "in": {"key": "bleeding_severity", "values": ["catastrophic"]}
    }
    rejects(build, flow, "invalid_condition_value")


def test_required_observations_must_match_the_conditions(
    build: Build, flow: dict[str, Any]
):
    state_of(flow, "assess_responsiveness")["requiredObservations"] = []
    rejects(build, flow, "required_observations_mismatch")


# ----------------------------------------------------- templates, actions, timers


def test_unknown_template_id_is_rejected(build: Build, flow: dict[str, Any]):
    state_of(flow, "assess_responsiveness")["instruction"]["templateId"] = "no.such"
    rejects(build, flow, "unknown_template_id")


def test_missing_instruction_template_reference_is_rejected(
    build: Build, flow: dict[str, Any]
):
    del state_of(flow, "assess_responsiveness")["instruction"]["templateId"]
    rejects(build, flow, "schema_violation")


def test_template_param_declaration_must_match_its_text(
    build: Build, flow: dict[str, Any], templates: dict[str, Any]
):
    for template in templates["templates"]:
        if template["id"] == "cpr.reminder":
            template["params"] = ["interval_seconds", "extra_unused"]
    with pytest.raises(RulePackageError) as excinfo:
        build(flow, templates)
    assert excinfo.value.detail == "template_param_mismatch"


def test_template_reference_must_supply_the_declared_params(
    build: Build, flow: dict[str, Any]
):
    state_of(flow, "cpr_in_progress")["instruction"]["params"] = {"depth_cm": 5}
    rejects(build, flow, "template_param_mismatch")


def test_a_notice_cannot_be_used_as_a_clinical_instruction(
    build: Build, flow: dict[str, Any]
):
    state_of(flow, "assess_responsiveness")["instruction"]["templateId"] = (
        "mode.on_call.notice"
    )
    rejects(build, flow, "template_kind_mismatch")


def test_unknown_action_kind_is_rejected(build: Build, flow: dict[str, Any]):
    state_of(flow, "assess_responsiveness")["actions"].append({"kind": "place_call"})
    rejects(build, flow, "unknown_action_kind")


def test_action_referencing_an_unknown_template_is_rejected(
    build: Build, flow: dict[str, Any]
):
    """An action intent cannot carry wording the package does not declare."""
    state = state_of(flow, "cpr_in_progress")
    speak = next(item for item in state["actions"] if item["kind"] == "speak_template")
    speak["params"]["template_id"] = "cpr.compresions"
    rejects(build, flow, "unknown_template_id")


def test_timer_reaction_action_referencing_an_unknown_template_is_rejected(
    build: Build, flow: dict[str, Any]
):
    entry = state_of(flow, "cpr_in_progress")["onTimer"][0]
    entry["actions"][0]["params"]["template_id"] = "cpr.remind"
    rejects(build, flow, "unknown_template_id")


def test_every_action_template_reference_in_the_demo_package_resolves():
    package = load_package(DEMO_RULE_VERSION)
    referenced = set()
    for state in package.states.values():
        for action in state.get("actions", []):
            referenced.add(action.get("params", {}).get("template_id"))
        for entry in state.get("onTimer", []):
            for action in entry.get("actions", []):
                referenced.add(action.get("params", {}).get("template_id"))
    referenced.discard(None)
    assert referenced
    assert referenced <= set(package.templates)


def test_observation_ids_are_restricted_to_an_ascii_charset():
    """Both runtimes must sort observation ids identically."""
    from app.services.rules.schemas import OBSERVATION_SCHEMA, get_schema

    schema = get_schema(OBSERVATION_SCHEMA)
    assert "pattern" in schema["properties"]["observationId"]


def test_unknown_timer_id_in_state_entry_is_rejected(build: Build, flow: dict[str, Any]):
    state_of(flow, "cpr_in_progress")["onEnterTimers"][0]["timerId"] = "no_such_timer"
    rejects(build, flow, "unknown_timer_id")


def test_unknown_timer_id_in_a_timer_reaction_is_rejected(
    build: Build, flow: dict[str, Any]
):
    state_of(flow, "cpr_in_progress")["onTimer"][0]["timerId"] = "no_such_timer"
    rejects(build, flow, "unknown_timer_id")


def test_two_reactions_to_one_timer_are_rejected(build: Build, flow: dict[str, Any]):
    state = state_of(flow, "cpr_in_progress")
    state["onTimer"].append(copy.deepcopy(state["onTimer"][0]))
    rejects(build, flow, "duplicate_timer_trigger")


def test_enum_observation_without_values_is_rejected(build: Build, flow: dict[str, Any]):
    for observation in flow["observations"]:
        if observation["key"] == "bleeding_severity":
            del observation["values"]
    rejects(build, flow, "invalid_observation_definition")


def test_non_enum_observation_with_values_is_rejected(build: Build, flow: dict[str, Any]):
    for observation in flow["observations"]:
        if observation["key"] == "responsive":
            observation["values"] = ["a", "b"]
    rejects(build, flow, "invalid_observation_definition")


def test_enum_observation_cannot_use_the_reserved_unknown_value(
    build: Build, flow: dict[str, Any]
):
    observation = next(item for item in flow["observations"] if item["type"] == "enum")
    observation["values"].append("unknown")
    rejects(build, flow, "invalid_observation_definition")


def test_non_integer_observation_cannot_declare_numeric_bounds(
    build: Build, flow: dict[str, Any]
):
    observation = next(item for item in flow["observations"] if item["type"] == "boolean")
    observation["minimum"] = 0
    rejects(build, flow, "invalid_observation_definition")


def test_integer_observation_minimum_cannot_exceed_maximum(
    build: Build, flow: dict[str, Any]
):
    observation = next(item for item in flow["observations"] if item["type"] == "integer")
    observation["minimum"] = 10
    observation["maximum"] = 5
    rejects(build, flow, "invalid_observation_definition")


# ----------------------------------------------------------------- rendering


def test_templates_render_declared_parameters_only():
    package = load_package(DEMO_RULE_VERSION)
    rendered = package.render("cpr.reminder", {"interval_seconds": 120})
    assert rendered["templateId"] == "cpr.reminder"
    assert rendered["kind"] == "critical_instruction"
    assert rendered["locale"] == "zh-TW"
    assert rendered["text"] == (
        "已按壓約 120 秒。若體力不支請立即換手，換手時保持按壓不中斷。"
    )
    assert "{" not in rendered["text"]


def test_rendering_does_not_honour_format_specifications():
    """Substitution is a plain text replacement, never a format expression."""
    package = load_package(DEMO_RULE_VERSION)
    rendered = package.render("cpr.reminder", {"interval_seconds": "{0.__class__}"})
    assert rendered["text"].count("{0.__class__}") == 1


def test_rendering_a_missing_parameter_is_rejected():
    package = load_package(DEMO_RULE_VERSION)
    with pytest.raises(RulePackageError) as excinfo:
        package.render("cpr.reminder", {})
    assert excinfo.value.detail == "template_param_mismatch"


def test_missing_rule_version_reports_the_expected_path(tmp_path):
    with pytest.raises(RulePackageError) as excinfo:
        load_package("demo-v0")
    assert excinfo.value.detail == "missing_flow_document"


def test_rule_version_is_validated_before_constructing_a_path(tmp_path):
    with pytest.raises(RulePackageError) as excinfo:
        load_package("../outside", tmp_path)
    assert excinfo.value.detail == "invalid_rule_version"


def test_templates_ref_is_schema_validated_before_file_lookup(
    tmp_path, flow: dict[str, Any]
):
    (tmp_path / "flows").mkdir()
    (tmp_path / "templates").mkdir()
    flow["templatesRef"] = "../outside.yaml"
    (tmp_path / "flows" / "demo-v1.flow.yaml").write_text(
        json.dumps(flow, ensure_ascii=False), encoding="utf-8"
    )

    with pytest.raises(RulePackageError) as excinfo:
        load_package("demo-v1", tmp_path)
    assert excinfo.value.detail == "schema_violation"
