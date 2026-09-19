"""Deterministic evaluation of a pinned clinical rule package.

The interpreter is a pure function of ``(package, request)``. It reads no clock,
performs no I/O, issues no external effect, and evaluates nothing beyond the
allowlisted condition operators. It proposes: the returned ``Decision`` carries
template references, action intents, timer operations, and the revisions the
caller must still check before applying anything.

Checks run in a fixed order so a malformed or stale request always fails the
same way: request schema, then ``rule_mismatch``, then semantic ``invalid_input``
(undeclared state, timer, or trigger shape), then ``stale_revision``.

Interpreter-owned reason codes, used where the package does not supply one:

``guidance_suspended``
    The mode policy stops clinical progression, as in ``handover``.
``mode_changed``
    An interaction-mode change re-applied the output policy without advancing
    the clinical state.
``timer_not_applicable``
    A declared timer elapsed but the current state defines no reaction to it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import conditions, observations as observations_module
from .errors import InvalidInputError, RuleMismatchError, StaleRevisionError
from .package import INTERPRETER_VERSION, RulePackage, load_package
from .schemas import (
    DECISION_SCHEMA,
    EVALUATION_REQUEST_SCHEMA,
    SUPPORTED_SCHEMA_VERSION,
    validate_against_schema,
)

DECISION_SCHEMA_VERSION = SUPPORTED_SCHEMA_VERSION


@dataclass(frozen=True)
class _TimerOp:
    op: str
    timer_id: str
    reason: str


class RuleInterpreter:
    """Evaluates one pinned rule package."""

    def __init__(self, package: RulePackage) -> None:
        self.package = package

    @classmethod
    def for_version(
        cls, rule_version: str, rules_dir: Path | str | None = None
    ) -> "RuleInterpreter":
        return cls(load_package(rule_version, rules_dir))

    # ------------------------------------------------------------------ public

    def evaluate(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Evaluate one request and return a decision in the shared JSON shape."""
        validate_against_schema(
            request,
            EVALUATION_REQUEST_SCHEMA,
            source="evaluation request",
            error_type=InvalidInputError,
            detail="schema_violation",
        )
        package = self.package

        if request["ruleVersion"] != package.rule_version:
            raise RuleMismatchError(
                f"request pins rule version {request['ruleVersion']!r} but the loaded "
                f"package is {package.rule_version!r}",
                detail="rule_version_mismatch",
            )
        if INTERPRETER_VERSION not in package.compatible_interpreter_versions:
            raise RuleMismatchError(
                f"interpreter {INTERPRETER_VERSION} is not compatible with package "
                f"{package.rule_version!r}",
                detail="interpreter_incompatible",
            )

        self._check_request_semantics(request)

        expected_state = request.get("expectedStateRevision")
        if expected_state is not None and expected_state != request["stateRevision"]:
            raise StaleRevisionError(
                f"expectedStateRevision {expected_state} does not match current "
                f"stateRevision {request['stateRevision']}",
                detail="state_revision",
            )
        expected_mode = request.get("expectedModeRevision")
        if expected_mode is not None and expected_mode != request["modeRevision"]:
            raise StaleRevisionError(
                f"expectedModeRevision {expected_mode} does not match current "
                f"modeRevision {request['modeRevision']}",
                detail="mode_revision",
            )

        resolved = observations_module.resolve(request["observations"], package)
        decision = self._decide(request, resolved)
        validate_against_schema(
            decision,
            DECISION_SCHEMA,
            source="decision",
            error_type=InvalidInputError,
            detail="decision_schema_violation",
        )
        return decision

    # ----------------------------------------------------------------- private

    def _check_request_semantics(self, request: Mapping[str, Any]) -> None:
        package = self.package
        if request["clinicalState"] not in package.states:
            raise InvalidInputError(
                f"clinicalState {request['clinicalState']!r} is not declared in "
                f"package {package.rule_version!r}",
                detail="unknown_state",
            )
        for timer in request["timers"]:
            if timer["timerId"] not in package.timers:
                raise InvalidInputError(
                    f"timer {timer['timerId']!r} is not declared in package "
                    f"{package.rule_version!r}",
                    detail="unknown_timer_id",
                )
        seen: set[str] = set()
        for observation in request["observations"]:
            if observation["observationId"] in seen:
                raise InvalidInputError(
                    f"duplicate observationId {observation['observationId']!r}",
                    detail="duplicate_observation_id",
                )
            seen.add(observation["observationId"])
            for field in ("observedAt", "receivedAt"):
                value = observation.get(field)
                if value is None:
                    continue
                try:
                    datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
                except (TypeError, ValueError) as exc:
                    raise InvalidInputError(
                        f"observation {observation['observationId']!r} has an "
                        f"invalid {field} value {value!r}",
                        detail="invalid_observation_timestamp",
                    ) from exc

        trigger = request["trigger"]
        if trigger["type"] == "timer":
            timer_id = trigger.get("timerId")
            if timer_id is None:
                raise InvalidInputError(
                    "a timer trigger must name a timerId", detail="missing_timer_id"
                )
            if timer_id not in package.timers:
                raise InvalidInputError(
                    f"timer {timer_id!r} is not declared in package "
                    f"{package.rule_version!r}",
                    detail="unknown_timer_id",
                )
        elif "timerId" in trigger:
            raise InvalidInputError(
                f"trigger type {trigger['type']!r} must not name a timerId",
                detail="unexpected_timer_id",
            )

    def _decide(
        self,
        request: Mapping[str, Any],
        resolved: observations_module.ResolvedObservations,
    ) -> dict[str, Any]:
        package = self.package
        state = package.states[request["clinicalState"]]
        policy = package.mode_policies[request["interactionMode"]]
        trigger = request["trigger"]

        notices: list[dict[str, Any]] = []
        if policy.notice_template_id is not None:
            notices.append(package.render(policy.notice_template_id, {}))
        if trigger["type"] == "resume" and package.resume_notice_template_id is not None:
            notices.append(package.render(package.resume_notice_template_id, {}))

        if not policy.guidance_active:
            to_state = state["id"]
            reason_code = "guidance_suspended"
            instruction = None
            candidate_actions: Sequence[Mapping[str, Any]] = state.get("actions", [])
            suppressed = [
                {
                    "kind": action["kind"],
                    "channel": package.action_channels[action["kind"]],
                    "reason": "guidance_suspended",
                }
                for action in candidate_actions
            ]
            actions: list[dict[str, Any]] = []
            timer_ops = self._mode_timer_ops(request, policy)
            state_changed = False
        else:
            (
                to_state,
                state_changed,
                reason_code,
                instruction_ref,
                candidate_actions,
                raw_timer_ops,
            ) = self._progress(request, state, resolved)
            instruction = (
                package.render(
                    instruction_ref["templateId"], instruction_ref.get("params", {})
                )
                if instruction_ref is not None
                else None
            )
            actions, suppressed = self._filter_actions(candidate_actions, policy)
            timer_ops = self._render_timer_ops(raw_timer_ops, policy)

        return {
            "schemaVersion": DECISION_SCHEMA_VERSION,
            "ruleVersion": package.rule_version,
            "reviewStatus": package.review_status,
            "interpreterVersion": INTERPRETER_VERSION,
            "incidentId": request["incidentId"],
            "trigger": dict(trigger),
            "interactionMode": request["interactionMode"],
            "modeRevision": request["modeRevision"],
            "guidanceActive": policy.guidance_active,
            "fromState": state["id"],
            "toState": to_state,
            "stateChanged": state_changed,
            "stateRevision": request["stateRevision"],
            "nextStateRevision": request["stateRevision"] + (1 if state_changed else 0),
            "reasonCode": reason_code,
            "acceptedObservationIds": list(resolved.accepted_ids),
            "rejectedObservations": [dict(item) for item in resolved.rejected],
            "resolvedObservations": resolved.as_output(),
            "unknownObservationKeys": list(resolved.unknown_keys),
            "conflictingObservationKeys": list(resolved.conflicting_keys),
            "instruction": instruction,
            "notices": notices,
            "actions": actions,
            "suppressedActions": suppressed,
            "timerOps": timer_ops,
            "outputChannels": ["screen", "audio"] if policy.audio_allowed else ["screen"],
        }

    def _progress(
        self,
        request: Mapping[str, Any],
        state: Mapping[str, Any],
        resolved: observations_module.ResolvedObservations,
    ) -> tuple[
        str,
        bool,
        str,
        Mapping[str, Any] | None,
        Sequence[Mapping[str, Any]],
        list[_TimerOp],
    ]:
        package = self.package
        trigger = request["trigger"]
        trigger_type = trigger["type"]

        if trigger_type == "timer":
            for entry in state.get("onTimer", []):
                if entry["timerId"] == trigger["timerId"]:
                    return (
                        state["id"],
                        False,
                        entry["reasonCode"],
                        entry.get("instruction", state.get("instruction")),
                        entry.get("actions", []),
                        [
                            _TimerOp(op["op"], op["timerId"], "timer_elapsed")
                            for op in entry.get("timerOps", [])
                        ],
                    )
            # A timer that this state does not react to changes nothing. It must
            # not invent a clinical step of its own.
            return (
                state["id"],
                False,
                "timer_not_applicable",
                state.get("instruction"),
                [],
                [],
            )

        if trigger_type == "mode_change":
            policy = package.mode_policies[request["interactionMode"]]
            return (
                state["id"],
                False,
                "mode_changed",
                state.get("instruction"),
                state.get("actions", []),
                self._running_timer_ops(request, "set_audible", "mode_policy")
                if policy.timer_policy != "paused"
                else self._running_timer_ops(request, "pause", "mode_policy"),
            )

        # observation and resume both evaluate the ordered transitions. A resume
        # restores paused timers and never replays reminders missed while the
        # page was hidden or the mode was silent.
        resume_ops: list[_TimerOp] = []
        if trigger_type == "resume":
            resume_ops = [
                _TimerOp("resume", timer["timerId"], "resume_after_interruption")
                for timer in self._timers_in_declaration_order(request)
                if timer["status"] == "paused"
            ]

        matched, saw_unknown = conditions.first_matching(
            [
                (transition["when"], transition)
                for transition in state["transitions"]
            ],
            resolved.values,
        )
        if matched is not None:
            target = package.states[matched["to"]]
            entry_ops = [
                _TimerOp(op["op"], op["timerId"], "state_entry")
                for op in target.get("onEnterTimers", [])
            ]
            # Entering a state re-establishes its whole timer plan, so it
            # supersedes the resume operations rather than stacking with them.
            return (
                target["id"],
                True,
                matched["reasonCode"],
                target.get("instruction"),
                target.get("actions", []),
                entry_ops,
            )

        outcome = state["onUnknown"] if saw_unknown else state["onUnmatched"]
        return (
            state["id"],
            False,
            outcome["reasonCode"],
            outcome.get("instruction", state.get("instruction")),
            state.get("actions", []),
            resume_ops,
        )

    def _timers_in_declaration_order(
        self, request: Mapping[str, Any]
    ) -> list[Mapping[str, Any]]:
        by_id = {timer["timerId"]: timer for timer in request["timers"]}
        return [
            by_id[timer_id]
            for timer_id in self.package.timer_order
            if timer_id in by_id
        ]

    def _running_timer_ops(
        self, request: Mapping[str, Any], op: str, reason: str
    ) -> list[_TimerOp]:
        return [
            _TimerOp(op, timer["timerId"], reason)
            for timer in self._timers_in_declaration_order(request)
            if timer["status"] == "running"
        ]

    def _mode_timer_ops(
        self, request: Mapping[str, Any], policy: Any
    ) -> list[dict[str, Any]]:
        """Timer operations for a mode that suspends guidance."""
        ops = self._running_timer_ops(request, "pause", "mode_policy")
        return self._render_timer_ops(ops, policy)

    def _render_timer_ops(
        self, ops: Sequence[_TimerOp], policy: Any
    ) -> list[dict[str, Any]]:
        audible = policy.audio_allowed and policy.timer_policy == "run"
        rendered = []
        for op in ops:
            definition = self.package.timers[op.timer_id]
            rendered.append(
                {
                    "op": op.op,
                    "timerId": definition.id,
                    "intervalMs": definition.interval_ms,
                    "repeat": definition.repeat,
                    "audible": audible,
                    "reason": op.reason,
                }
            )
        return rendered

    def _filter_actions(
        self, actions: Sequence[Mapping[str, Any]], policy: Any
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        allowed: list[dict[str, Any]] = []
        suppressed: list[dict[str, Any]] = []
        for action in actions:
            channel = self.package.action_channels[action["kind"]]
            if channel == "audio" and not policy.audio_allowed:
                suppressed.append(
                    {
                        "kind": action["kind"],
                        "channel": channel,
                        "reason": "audio_not_allowed",
                    }
                )
                continue
            allowed.append(
                {
                    "kind": action["kind"],
                    "channel": channel,
                    "params": dict(action.get("params", {})),
                }
            )
        return allowed, suppressed
