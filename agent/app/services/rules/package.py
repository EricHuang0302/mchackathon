"""Loading and validation of a versioned clinical rule package.

A package is the pair (flow document, template document) that share one
``ruleVersion``. Loading always validates; there is no way to obtain a package
object that skipped a check. Validation covers what JSON Schema can express plus
the cross-reference rules it cannot: dangling transition targets, undeclared
observation keys, unknown template or action or timer identifiers, template
parameter mismatches, and required-observation consistency.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from . import conditions
from .errors import RuleMismatchError, RulePackageError
from .restricted_yaml import load_restricted_yaml, normalize_source
from .schemas import (
    RULE_PACKAGE_SCHEMA,
    RULE_TEMPLATES_SCHEMA,
    SUPPORTED_SCHEMA_VERSION,
    default_rules_dir,
    validate_against_schema,
)

#: Version of this interpreter. A package must list it in
#: ``compatibleInterpreterVersions`` or evaluation fails with ``rule_mismatch``.
INTERPRETER_VERSION = "1.0"

INTERACTION_MODES = ("call_119", "on_call", "voice_guidance", "handover")

_PLACEHOLDER_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")
_RULE_VERSION_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class ObservationDefinition:
    key: str
    type: str
    minimum_confirmation: str
    values: tuple[str, ...] | None = None
    minimum: int | None = None
    maximum: int | None = None

    def accepts(self, value: Any) -> bool:
        """Report whether ``value`` is a valid value for this key."""
        if self.type == "boolean":
            return isinstance(value, bool)
        if self.type == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                return False
            if self.minimum is not None and value < self.minimum:
                return False
            if self.maximum is not None and value > self.maximum:
                return False
            return True
        return isinstance(value, str) and value in (self.values or ())


@dataclass(frozen=True)
class TimerDefinition:
    id: str
    interval_ms: int
    repeat: bool


@dataclass(frozen=True)
class ModePolicy:
    audio_allowed: bool
    guidance_active: bool
    timer_policy: str
    notice_template_id: str | None


@dataclass(frozen=True)
class Template:
    id: str
    kind: str
    params: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class RulePackage:
    rule_version: str
    schema_version: str
    locale: str
    review_status: str
    clinical_review_required: bool
    compatible_interpreter_versions: tuple[str, ...]
    supported_populations: tuple[str, ...]
    excluded_populations: tuple[str, ...]
    clinical_references: tuple[Mapping[str, Any], ...]
    resume_notice_template_id: str | None
    initial_state: str
    content_hash: str
    observations: Mapping[str, ObservationDefinition]
    action_channels: Mapping[str, str]
    action_order: tuple[str, ...]
    timers: Mapping[str, TimerDefinition]
    timer_order: tuple[str, ...]
    mode_policies: Mapping[str, ModePolicy]
    states: Mapping[str, Mapping[str, Any]]
    state_order: tuple[str, ...]
    templates: Mapping[str, Template]
    source_paths: tuple[str, ...] = field(default=())

    def state(self, state_id: str) -> Mapping[str, Any]:
        return self.states[state_id]

    def render(self, template_id: str, params: Mapping[str, Any]) -> dict[str, Any]:
        """Render one approved template.

        Substitution is a plain textual replacement of declared placeholders.
        No expression is evaluated, no format specification is honoured, and an
        undeclared placeholder cannot appear because loading rejects it.
        """
        template = self.templates[template_id]
        missing = set(template.params) - set(params)
        if missing:
            raise RulePackageError(
                f"template {template_id!r} is missing parameters {sorted(missing)}",
                detail="template_param_mismatch",
            )
        text = _PLACEHOLDER_RE.sub(lambda m: str(params[m.group(1)]), template.text)
        return {
            "templateId": template.id,
            "kind": template.kind,
            "locale": self.locale,
            "text": text,
            "params": {name: params[name] for name in template.params},
        }


def compute_content_hash(parts: list[tuple[str, str]]) -> str:
    """Hash the normalized source of the documents making up a package.

    ``parts`` is an ordered list of ``(file name, text)``. The text is line-ending
    and BOM normalized first, so the same checkout hashes identically on Windows
    and on Linux. Both runtimes can reproduce this value from the same files.
    """
    digest = hashlib.sha256()
    for name, text in parts:
        digest.update(name.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(normalize_source(text).encode("utf-8"))
        digest.update(b"\x00")
    return f"sha256:{digest.hexdigest()}"


def _require_unique(items: list[str], *, what: str, detail: str) -> None:
    seen: set[str] = set()
    for item in items:
        if item in seen:
            raise RulePackageError(f"duplicate {what} {item!r}", detail=detail)
        seen.add(item)


def _iter_template_refs(flow: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    """Collect every (expected template kind, templateRef) in the flow."""
    refs: list[tuple[str, Mapping[str, Any]]] = []
    for policy in flow["modePolicies"].values():
        if policy["noticeTemplateId"] is not None:
            refs.append(("notice", {"templateId": policy["noticeTemplateId"]}))
    if flow["resumeNoticeTemplateId"] is not None:
        refs.append(("notice", {"templateId": flow["resumeNoticeTemplateId"]}))
    for state in flow["states"]:
        for key in ("instruction",):
            if key in state:
                refs.append(("critical_instruction", state[key]))
        for outcome_key in ("onUnknown", "onUnmatched"):
            outcome = state[outcome_key]
            if "instruction" in outcome:
                refs.append(("critical_instruction", outcome["instruction"]))
        for entry in state.get("onTimer", []):
            if "instruction" in entry:
                refs.append(("critical_instruction", entry["instruction"]))
    return refs


def _validate_templates_document(document: Mapping[str, Any], source: str) -> dict[str, Template]:
    validate_against_schema(document, RULE_TEMPLATES_SCHEMA, source=source)
    if document["schemaVersion"] != SUPPORTED_SCHEMA_VERSION:
        raise RulePackageError(
            f"{source}: unsupported schemaVersion {document['schemaVersion']!r}",
            detail="unsupported_schema_version",
        )
    _require_unique(
        [item["id"] for item in document["templates"]],
        what="template id",
        detail="duplicate_template_id",
    )
    templates: dict[str, Template] = {}
    for item in document["templates"]:
        placeholders = set(_PLACEHOLDER_RE.findall(item["text"]))
        declared = set(item["params"])
        if placeholders != declared:
            raise RulePackageError(
                f"{source}: template {item['id']!r} declares params "
                f"{sorted(declared)} but its text uses {sorted(placeholders)}",
                detail="template_param_mismatch",
            )
        templates[item["id"]] = Template(
            id=item["id"],
            kind=item["kind"],
            params=tuple(item["params"]),
            text=item["text"],
        )
    return templates


def _validate_condition(
    condition: Any,
    observations: Mapping[str, ObservationDefinition],
    *,
    where: str,
) -> None:
    operator, operand = conditions.operator_of(condition)
    if operator in ("all", "any"):
        for child in operand:
            _validate_condition(child, observations, where=where)
        return
    if operator == "not":
        _validate_condition(operand, observations, where=where)
        return

    key = operand["key"]
    definition = observations.get(key)
    if definition is None:
        raise RulePackageError(
            f"{where}: condition references undeclared observation key {key!r}",
            detail="unknown_observation_key",
        )
    if operator in conditions.NUMERIC_OPERATORS and definition.type != "integer":
        raise RulePackageError(
            f"{where}: operator {operator!r} needs an integer observation, "
            f"but {key!r} is declared as {definition.type!r}",
            detail="invalid_condition_value",
        )
    if operator == "eq" and not definition.accepts(operand["value"]):
        raise RulePackageError(
            f"{where}: value {operand['value']!r} is not valid for observation {key!r}",
            detail="invalid_condition_value",
        )
    if operator == "in":
        for item in operand["values"]:
            if not definition.accepts(item):
                raise RulePackageError(
                    f"{where}: value {item!r} is not valid for observation {key!r}",
                    detail="invalid_condition_value",
                )


def build_package(
    flow: Mapping[str, Any],
    templates_document: Mapping[str, Any],
    *,
    flow_source: str,
    templates_source: str,
    content_hash: str,
) -> RulePackage:
    """Validate two already-parsed documents and build a ``RulePackage``."""
    validate_against_schema(flow, RULE_PACKAGE_SCHEMA, source=flow_source)
    if flow["schemaVersion"] != SUPPORTED_SCHEMA_VERSION:
        raise RulePackageError(
            f"{flow_source}: unsupported schemaVersion {flow['schemaVersion']!r}",
            detail="unsupported_schema_version",
        )
    if INTERPRETER_VERSION not in flow["compatibleInterpreterVersions"]:
        raise RuleMismatchError(
            f"{flow_source}: interpreter {INTERPRETER_VERSION} is not listed in "
            f"compatibleInterpreterVersions {flow['compatibleInterpreterVersions']}",
            detail="interpreter_incompatible",
        )

    templates = _validate_templates_document(templates_document, templates_source)
    for field_name in ("ruleVersion", "locale", "reviewStatus"):
        if templates_document[field_name] != flow[field_name]:
            raise RulePackageError(
                f"{templates_source}: {field_name} "
                f"{templates_document[field_name]!r} does not match the flow value "
                f"{flow[field_name]!r}",
                detail="templates_manifest_mismatch",
            )

    _require_unique(
        [item["key"] for item in flow["observations"]],
        what="observation key",
        detail="duplicate_observation_key",
    )
    observations: dict[str, ObservationDefinition] = {}
    for item in flow["observations"]:
        if item["type"] == "enum" and "values" not in item:
            raise RulePackageError(
                f"{flow_source}: enum observation {item['key']!r} declares no values",
                detail="invalid_observation_definition",
            )
        if item["type"] != "enum" and "values" in item:
            raise RulePackageError(
                f"{flow_source}: observation {item['key']!r} of type "
                f"{item['type']!r} must not declare values",
                detail="invalid_observation_definition",
            )
        if item["type"] == "enum" and "unknown" in item.get("values", []):
            raise RulePackageError(
                f"{flow_source}: enum observation {item['key']!r} uses reserved "
                "value 'unknown'",
                detail="invalid_observation_definition",
            )
        has_bounds = "minimum" in item or "maximum" in item
        if item["type"] != "integer" and has_bounds:
            raise RulePackageError(
                f"{flow_source}: non-integer observation {item['key']!r} "
                "must not declare numeric bounds",
                detail="invalid_observation_definition",
            )
        if (
            item["type"] == "integer"
            and "minimum" in item
            and "maximum" in item
            and item["minimum"] > item["maximum"]
        ):
            raise RulePackageError(
                f"{flow_source}: observation {item['key']!r} has minimum greater "
                "than maximum",
                detail="invalid_observation_definition",
            )
        observations[item["key"]] = ObservationDefinition(
            key=item["key"],
            type=item["type"],
            minimum_confirmation=item["minimumConfirmation"],
            values=tuple(item["values"]) if "values" in item else None,
            minimum=item.get("minimum"),
            maximum=item.get("maximum"),
        )

    _require_unique(
        [item["id"] for item in flow["actionKinds"]],
        what="action kind",
        detail="duplicate_action_kind",
    )
    action_channels = {item["id"]: item["channel"] for item in flow["actionKinds"]}
    action_order = tuple(item["id"] for item in flow["actionKinds"])

    _require_unique(
        [item["id"] for item in flow["timers"]],
        what="timer id",
        detail="duplicate_timer_id",
    )
    timers = {
        item["id"]: TimerDefinition(
            id=item["id"], interval_ms=item["intervalMs"], repeat=item["repeat"]
        )
        for item in flow["timers"]
    }
    timer_order = tuple(item["id"] for item in flow["timers"])

    _require_unique(
        [state["id"] for state in flow["states"]],
        what="state id",
        detail="duplicate_state_id",
    )
    states = {state["id"]: state for state in flow["states"]}
    state_order = tuple(state["id"] for state in flow["states"])

    if flow["initialState"] not in states:
        raise RulePackageError(
            f"{flow_source}: initialState {flow['initialState']!r} is not a declared state",
            detail="unknown_initial_state",
        )

    for expected_kind, ref in _iter_template_refs(flow):
        template = templates.get(ref["templateId"])
        if template is None:
            raise RulePackageError(
                f"{flow_source}: unknown template id {ref['templateId']!r}",
                detail="unknown_template_id",
            )
        if template.kind != expected_kind:
            raise RulePackageError(
                f"{flow_source}: template {template.id!r} is a {template.kind!r} "
                f"but is referenced as a {expected_kind!r}",
                detail="template_kind_mismatch",
            )
        declared = set(template.params)
        supplied = set(ref.get("params", {}))
        if declared != supplied:
            raise RulePackageError(
                f"{flow_source}: reference to template {template.id!r} supplies "
                f"params {sorted(supplied)} but the template declares {sorted(declared)}",
                detail="template_param_mismatch",
            )

    def check_action(action: Mapping[str, Any], where: str) -> None:
        if action["kind"] not in action_channels:
            raise RulePackageError(
                f"{where}: unknown action kind {action['kind']!r}",
                detail="unknown_action_kind",
            )
        # An action that names approved wording must name wording that exists,
        # otherwise a dangling template id reaches the adapter inside an intent.
        template_id = action.get("params", {}).get("template_id")
        if template_id is not None and template_id not in templates:
            raise RulePackageError(
                f"{where}: action {action['kind']!r} references unknown template id "
                f"{template_id!r}",
                detail="unknown_template_id",
            )

    for state in flow["states"]:
        where = f"{flow_source}: state {state['id']!r}"
        _require_unique(
            [transition["id"] for transition in state["transitions"]],
            what=f"transition id in state {state['id']!r}",
            detail="duplicate_transition_id",
        )
        if state["kind"] == "guidance" and not state["transitions"]:
            raise RulePackageError(
                f"{where} is a guidance state but declares no transitions",
                detail="guidance_state_has_no_transitions",
            )
        if state["kind"] != "guidance" and state["transitions"]:
            raise RulePackageError(
                f"{where} is {state['kind']!r} but declares transitions",
                detail="terminal_state_has_transitions",
            )

        referenced: set[str] = set()
        for transition in state["transitions"]:
            if transition["to"] not in states:
                raise RulePackageError(
                    f"{where}: transition {transition['id']!r} targets undeclared "
                    f"state {transition['to']!r}",
                    detail="dangling_transition_target",
                )
            _validate_condition(transition["when"], observations, where=where)
            referenced |= conditions.referenced_keys(transition["when"])

        declared_required = set(state["requiredObservations"])
        if declared_required != referenced:
            raise RulePackageError(
                f"{where}: requiredObservations {sorted(declared_required)} does not "
                f"match the keys its transitions read {sorted(referenced)}",
                detail="required_observations_mismatch",
            )

        for action in state.get("actions", []):
            check_action(action, where)
        for timer_op in state.get("onEnterTimers", []):
            if timer_op["timerId"] not in timers:
                raise RulePackageError(
                    f"{where}: unknown timer id {timer_op['timerId']!r}",
                    detail="unknown_timer_id",
                )
        seen_timer_triggers: set[str] = set()
        for entry in state.get("onTimer", []):
            if entry["timerId"] not in timers:
                raise RulePackageError(
                    f"{where}: unknown timer id {entry['timerId']!r}",
                    detail="unknown_timer_id",
                )
            if entry["timerId"] in seen_timer_triggers:
                raise RulePackageError(
                    f"{where}: more than one onTimer entry for {entry['timerId']!r}",
                    detail="duplicate_timer_trigger",
                )
            seen_timer_triggers.add(entry["timerId"])
            for action in entry.get("actions", []):
                check_action(action, where)
            for timer_op in entry.get("timerOps", []):
                if timer_op["timerId"] not in timers:
                    raise RulePackageError(
                        f"{where}: unknown timer id {timer_op['timerId']!r}",
                        detail="unknown_timer_id",
                    )

    mode_policies = {
        mode: ModePolicy(
            audio_allowed=policy["audioAllowed"],
            guidance_active=policy["guidanceActive"],
            timer_policy=policy["timerPolicy"],
            notice_template_id=policy["noticeTemplateId"],
        )
        for mode, policy in flow["modePolicies"].items()
    }

    return RulePackage(
        rule_version=flow["ruleVersion"],
        schema_version=flow["schemaVersion"],
        locale=flow["locale"],
        review_status=flow["reviewStatus"],
        clinical_review_required=flow["clinicalReviewRequired"],
        compatible_interpreter_versions=tuple(flow["compatibleInterpreterVersions"]),
        supported_populations=tuple(flow["supportedPopulations"]),
        excluded_populations=tuple(flow["excludedPopulations"]),
        clinical_references=tuple(flow["clinicalReferences"]),
        resume_notice_template_id=flow["resumeNoticeTemplateId"],
        initial_state=flow["initialState"],
        content_hash=content_hash,
        observations=observations,
        action_channels=action_channels,
        action_order=action_order,
        timers=timers,
        timer_order=timer_order,
        mode_policies=mode_policies,
        states=states,
        state_order=state_order,
        templates=templates,
        source_paths=(flow_source, templates_source),
    )


def load_package_from_text(
    flow_text: str,
    templates_text: str,
    *,
    flow_source: str = "<flow>",
    templates_source: str = "<templates>",
) -> RulePackage:
    """Parse and validate a package from two in-memory documents."""
    flow = load_restricted_yaml(flow_text, source=flow_source)
    templates_document = load_restricted_yaml(templates_text, source=templates_source)
    content_hash = compute_content_hash(
        [(flow_source, flow_text), (templates_source, templates_text)]
    )
    return build_package(
        flow,
        templates_document,
        flow_source=flow_source,
        templates_source=templates_source,
        content_hash=content_hash,
    )


def load_package(rule_version: str, rules_dir: Path | str | None = None) -> RulePackage:
    """Load the pinned rule package for ``rule_version`` from ``rules/``."""
    if not isinstance(rule_version, str) or _RULE_VERSION_RE.fullmatch(rule_version) is None:
        raise RulePackageError(
            f"invalid rule version identifier {rule_version!r}",
            detail="invalid_rule_version",
        )
    base = Path(rules_dir) if rules_dir is not None else default_rules_dir()
    flow_path = base / "flows" / f"{rule_version}.flow.yaml"
    if not flow_path.is_file():
        raise RulePackageError(
            f"no flow document for rule version {rule_version!r} at {flow_path}",
            detail="missing_flow_document",
        )
    flow_text = flow_path.read_text(encoding="utf-8")
    flow = load_restricted_yaml(flow_text, source=flow_path.name)
    # Validate the complete manifest before dereferencing any package-supplied
    # path. In particular, templatesRef must satisfy the filename-only pattern
    # before it can influence a filesystem lookup.
    validate_against_schema(flow, RULE_PACKAGE_SCHEMA, source=flow_path.name)
    templates_path = base / "templates" / flow["templatesRef"]
    if not templates_path.is_file():
        raise RulePackageError(
            f"{flow_path.name}: templatesRef {flow['templatesRef']!r} not found at "
            f"{templates_path}",
            detail="missing_templates_document",
        )
    templates_text = templates_path.read_text(encoding="utf-8")
    templates_document = load_restricted_yaml(templates_text, source=templates_path.name)
    content_hash = compute_content_hash(
        [(flow_path.name, flow_text), (templates_path.name, templates_text)]
    )
    package = build_package(
        flow,
        templates_document,
        flow_source=flow_path.name,
        templates_source=templates_path.name,
        content_hash=content_hash,
    )
    if package.rule_version != rule_version:
        raise RulePackageError(
            f"{flow_path.name}: declares ruleVersion {package.rule_version!r} but was "
            f"loaded as {rule_version!r}",
            detail="rule_version_mismatch",
        )
    return package
