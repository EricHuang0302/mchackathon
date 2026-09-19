import { ruleError } from "./errors";
import { accepts, INTERPRETER_VERSION, operatorOf } from "./package";
import { schemaIds, validateSchema } from "./schema";
import type {
  Condition,
  Decision,
  EvaluationRequest,
  Observation,
  ObservationValue,
  RenderedTemplate,
  RuleAction,
  RulePackage,
  RuleState,
  TemplateRef,
} from "./types";

const UNKNOWN = Symbol("unknown");
type ResolvedValue = ObservationValue | typeof UNKNOWN;
type Tri = "true" | "false" | "unknown";

const CONFIRMATION_RANK = { proposed: 1, reported: 2, confirmed: 3 } as const;
const SOURCE_MAX = {
  button: "confirmed",
  voice_report: "reported",
  dispatcher_report: "confirmed",
  camera_proposal: "proposed",
  model_proposal: "proposed",
  system: "reported",
} as const;

interface ResolvedObservations {
  values: Record<string, ResolvedValue>;
  acceptedIds: string[];
  rejected: Decision["rejectedObservations"];
  unknownKeys: string[];
  conflictingKeys: string[];
}

interface RawTimerOp {
  op: Decision["timerOps"][number]["op"];
  timerId: string;
  reason: Decision["timerOps"][number]["reason"];
}

interface Progress {
  toState: string;
  stateChanged: boolean;
  reasonCode: string;
  instruction?: TemplateRef;
  actions: RuleAction[];
  timerOps: RawTimerOp[];
}

export class RuleEvaluator {
  constructor(readonly rulePackage: RulePackage) {}

  evaluate(input: unknown): Decision {
    validateSchema(schemaIds.evaluationRequest, input, "evaluation request", "invalid_input", "schema_violation");
    const request = input as EvaluationRequest;
    if (request.ruleVersion !== this.rulePackage.ruleVersion) {
      ruleError("rule_mismatch", "rule_version_mismatch", `Request pins ${request.ruleVersion}, loaded ${this.rulePackage.ruleVersion}`);
    }
    if (!this.rulePackage.compatibleInterpreterVersions.includes(INTERPRETER_VERSION)) {
      ruleError("rule_mismatch", "interpreter_incompatible", `Interpreter ${INTERPRETER_VERSION} is not compatible`);
    }
    this.checkSemantics(request);
    if (request.expectedStateRevision != null && request.expectedStateRevision !== request.stateRevision) {
      ruleError("stale_revision", "state_revision", "Expected state revision does not match current revision");
    }
    if (request.expectedModeRevision != null && request.expectedModeRevision !== request.modeRevision) {
      ruleError("stale_revision", "mode_revision", "Expected mode revision does not match current revision");
    }

    const decision = this.decide(request, resolveObservations(request.observations, this.rulePackage));
    validateSchema(schemaIds.decision, decision, "decision", "invalid_input", "decision_schema_violation");
    return decision;
  }

  private checkSemantics(request: EvaluationRequest): void {
    if (!this.rulePackage.states[request.clinicalState]) ruleError("invalid_input", "unknown_state", `Unknown state ${request.clinicalState}`);
    for (const timer of request.timers) {
      if (!this.rulePackage.timers[timer.timerId]) ruleError("invalid_input", "unknown_timer_id", `Unknown timer ${timer.timerId}`);
    }
    const ids = new Set<string>();
    for (const observation of request.observations) {
      if (ids.has(observation.observationId)) ruleError("invalid_input", "duplicate_observation_id", `Duplicate observation ${observation.observationId}`);
      ids.add(observation.observationId);
      for (const value of [observation.observedAt, observation.receivedAt]) {
        if (value !== undefined && !validTimestamp(value)) ruleError("invalid_input", "invalid_observation_timestamp", `Invalid observation timestamp ${value}`);
      }
    }
    if (request.trigger.type === "timer") {
      if (!request.trigger.timerId) ruleError("invalid_input", "missing_timer_id", "Timer trigger requires timerId");
      if (!this.rulePackage.timers[request.trigger.timerId]) ruleError("invalid_input", "unknown_timer_id", `Unknown timer ${request.trigger.timerId}`);
    } else if (request.trigger.timerId !== undefined) {
      ruleError("invalid_input", "unexpected_timer_id", `${request.trigger.type} must not name timerId`);
    }
  }

  private decide(request: EvaluationRequest, resolved: ResolvedObservations): Decision {
    const state = this.rulePackage.states[request.clinicalState];
    const policy = this.rulePackage.modePolicies[request.interactionMode];
    if (!state || !policy) ruleError("invalid_input", "unknown_state", "State or mode is unavailable");

    const notices: RenderedTemplate[] = [];
    if (policy.noticeTemplateId) notices.push(this.render({ templateId: policy.noticeTemplateId }));
    if (request.trigger.type === "resume" && this.rulePackage.resumeNoticeTemplateId) {
      notices.push(this.render({ templateId: this.rulePackage.resumeNoticeTemplateId }));
    }

    let progress: Progress;
    let instruction: RenderedTemplate | null;
    let actions: Decision["actions"];
    let suppressedActions: Decision["suppressedActions"];
    let timerOps: Decision["timerOps"];

    if (!policy.guidanceActive) {
      const candidates = state.actions ?? [];
      progress = {
        toState: state.id,
        stateChanged: false,
        reasonCode: "guidance_suspended",
        actions: candidates,
        timerOps: this.runningTimerOps(request, "pause", "mode_policy"),
      };
      instruction = null;
      actions = [];
      suppressedActions = candidates.map((action) => ({
        kind: action.kind,
        channel: this.channel(action),
        reason: "guidance_suspended",
      }));
      timerOps = this.renderTimerOps(progress.timerOps, policy);
    } else {
      progress = this.progress(request, state, resolved.values);
      instruction = progress.instruction ? this.render(progress.instruction) : null;
      ({ actions, suppressedActions } = this.filterActions(progress.actions, policy.audioAllowed));
      timerOps = this.renderTimerOps(progress.timerOps, policy);
    }

    const decision: Decision = {
      schemaVersion: "1.0.0",
      ruleVersion: this.rulePackage.ruleVersion,
      reviewStatus: this.rulePackage.reviewStatus,
      interpreterVersion: INTERPRETER_VERSION,
      incidentId: request.incidentId,
      trigger: { ...request.trigger },
      interactionMode: request.interactionMode,
      modeRevision: request.modeRevision,
      guidanceActive: policy.guidanceActive,
      fromState: state.id,
      toState: progress.toState,
      stateChanged: progress.stateChanged,
      stateRevision: request.stateRevision,
      nextStateRevision: request.stateRevision + (progress.stateChanged ? 1 : 0),
      reasonCode: progress.reasonCode,
      acceptedObservationIds: resolved.acceptedIds,
      rejectedObservations: resolved.rejected,
      resolvedObservations: Object.fromEntries(
        Object.entries(resolved.values).sort(([left], [right]) => asciiCompare(left, right)).map(([key, value]) => [key, value === UNKNOWN ? "unknown" : value]),
      ),
      unknownObservationKeys: resolved.unknownKeys,
      conflictingObservationKeys: resolved.conflictingKeys,
      instruction,
      notices,
      actions,
      suppressedActions,
      timerOps,
      outputChannels: policy.audioAllowed ? ["screen", "audio"] : ["screen"],
    };
    return decision;
  }

  private progress(request: EvaluationRequest, state: RuleState, values: Record<string, ResolvedValue>): Progress {
    if (request.trigger.type === "timer") {
      const reaction = (state.onTimer ?? []).find((entry) => entry.timerId === request.trigger.timerId);
      if (!reaction) {
        return { toState: state.id, stateChanged: false, reasonCode: "timer_not_applicable", instruction: state.instruction, actions: [], timerOps: [] };
      }
      return {
        toState: state.id,
        stateChanged: false,
        reasonCode: reaction.reasonCode,
        instruction: reaction.instruction ?? state.instruction,
        actions: reaction.actions ?? [],
        timerOps: (reaction.timerOps ?? []).map((item) => ({ ...item, reason: "timer_elapsed" })),
      };
    }
    if (request.trigger.type === "mode_change") {
      const policy = this.rulePackage.modePolicies[request.interactionMode];
      return {
        toState: state.id,
        stateChanged: false,
        reasonCode: "mode_changed",
        instruction: state.instruction,
        actions: state.actions ?? [],
        timerOps: policy.timerPolicy === "paused"
          ? this.runningTimerOps(request, "pause", "mode_policy")
          : this.runningTimerOps(request, "set_audible", "mode_policy"),
      };
    }

    const resumeOps = request.trigger.type === "resume"
      ? this.orderedTimers(request).filter((timer) => timer.status === "paused").map((timer) => ({ op: "resume" as const, timerId: timer.timerId, reason: "resume_after_interruption" as const }))
      : [];
    let sawUnknown = false;
    for (const transition of state.transitions) {
      const result = evaluateCondition(transition.when, values);
      if (result === "true") {
        const target = this.rulePackage.states[transition.to];
        if (!target) ruleError("invalid_rule_package", "dangling_transition_target", `Unknown state ${transition.to}`);
        return {
          toState: target.id,
          stateChanged: true,
          reasonCode: transition.reasonCode,
          instruction: target.instruction,
          actions: target.actions ?? [],
          timerOps: (target.onEnterTimers ?? []).map((item) => ({ ...item, reason: "state_entry" })),
        };
      }
      if (result === "unknown") sawUnknown = true;
    }
    const outcome = sawUnknown ? state.onUnknown : state.onUnmatched;
    return {
      toState: state.id,
      stateChanged: false,
      reasonCode: outcome.reasonCode,
      instruction: outcome.instruction ?? state.instruction,
      actions: state.actions ?? [],
      timerOps: resumeOps,
    };
  }

  private orderedTimers(request: EvaluationRequest): EvaluationRequest["timers"] {
    const byId = new Map(request.timers.map((timer) => [timer.timerId, timer]));
    return this.rulePackage.timerOrder.flatMap((id) => byId.has(id) ? [byId.get(id)!] : []);
  }

  private runningTimerOps(request: EvaluationRequest, op: RawTimerOp["op"], reason: RawTimerOp["reason"]): RawTimerOp[] {
    return this.orderedTimers(request).filter((timer) => timer.status === "running").map((timer) => ({ op, timerId: timer.timerId, reason }));
  }

  private renderTimerOps(ops: RawTimerOp[], policy: RulePackage["modePolicies"][EvaluationRequest["interactionMode"]]): Decision["timerOps"] {
    return ops.map((op) => {
      const timer = this.rulePackage.timers[op.timerId];
      if (!timer) ruleError("invalid_rule_package", "unknown_timer_id", `Unknown timer ${op.timerId}`);
      return { ...op, intervalMs: timer.intervalMs, repeat: timer.repeat, audible: policy.audioAllowed && policy.timerPolicy === "run" };
    });
  }

  private filterActions(candidates: RuleAction[], audioAllowed: boolean): Pick<Decision, "actions" | "suppressedActions"> {
    const actions: Decision["actions"] = [];
    const suppressedActions: Decision["suppressedActions"] = [];
    for (const action of candidates) {
      const channel = this.channel(action);
      if (channel === "audio" && !audioAllowed) {
        suppressedActions.push({ kind: action.kind, channel, reason: "audio_not_allowed" });
      } else {
        actions.push({ kind: action.kind, channel, params: { ...(action.params ?? {}) } });
      }
    }
    return { actions, suppressedActions };
  }

  private channel(action: RuleAction): "screen" | "audio" {
      const channel = this.rulePackage.actionChannels[action.kind];
    if (!channel) ruleError("invalid_rule_package", "unknown_action_kind", `Unknown action ${action.kind}`);
    return channel;
  }

  private render(ref: TemplateRef): RenderedTemplate {
    const template = this.rulePackage.templates[ref.templateId];
    if (!template) ruleError("invalid_rule_package", "unknown_template_id", `Unknown template ${ref.templateId}`);
    const params = ref.params ?? {};
    for (const name of template.params) {
      if (!(name in params)) ruleError("invalid_rule_package", "template_param_mismatch", `Missing template parameter ${name}`);
    }
    return {
      templateId: template.id,
      kind: template.kind,
      locale: this.rulePackage.locale,
      text: template.text.replace(/\{([a-z][a-z0-9_]*)\}/g, (_match, name: string) => String(params[name])),
      params: Object.fromEntries(template.params.map((name) => [name, params[name]])),
    };
  }
}

function resolveObservations(observations: Observation[], rulePackage: RulePackage): ResolvedObservations {
  const acceptedIds: string[] = [];
  const rejected: Decision["rejectedObservations"] = [];
  const candidates = new Map<string, Observation[]>();
  for (const observation of observations) {
    const definition = rulePackage.observations[observation.key];
    let code: Decision["rejectedObservations"][number]["code"] | undefined;
    if (!definition) code = "unknown_observation_key";
    else if (observation.value !== "unknown" && !accepts(definition, observation.value)) code = "invalid_value";
    else if (CONFIRMATION_RANK[observation.confirmation] > CONFIRMATION_RANK[SOURCE_MAX[observation.source]]) code = "source_cannot_confirm";
    else if (CONFIRMATION_RANK[observation.confirmation] < CONFIRMATION_RANK[definition.minimumConfirmation]) code = "insufficient_confirmation";
    if (code) {
      rejected.push({ observationId: observation.observationId, key: observation.key, code });
      continue;
    }
    acceptedIds.push(observation.observationId);
    candidates.set(observation.key, [...(candidates.get(observation.key) ?? []), observation]);
  }

  const values = Object.fromEntries(Object.keys(rulePackage.observations).map((key) => [key, UNKNOWN])) as Record<string, ResolvedValue>;
  const conflictingKeys: string[] = [];
  for (const [key, group] of candidates) {
    const bestRank = Math.max(...group.map((item) => CONFIRMATION_RANK[item.confirmation]));
    const ranked = group.filter((item) => CONFIRMATION_RANK[item.confirmation] === bestRank);
    const latest = ranked.reduce((value, item) => item.observedAt > value ? item.observedAt : value, "");
    const top = ranked.filter((item) => item.observedAt === latest);
    if (new Set(top.map((item) => `${typeof item.value}:${JSON.stringify(item.value)}`)).size > 1) {
      conflictingKeys.push(key);
      continue;
    }
    const winner = top[0]?.value;
    if (winner !== undefined && winner !== "unknown") values[key] = winner;
  }
  const unknownKeys = Object.entries(values).filter(([, value]) => value === UNKNOWN).map(([key]) => key).sort(asciiCompare);
  return {
    values,
    acceptedIds: acceptedIds.sort(asciiCompare),
    rejected: rejected.sort((left, right) => asciiCompare(left.observationId, right.observationId)),
    unknownKeys,
    conflictingKeys: conflictingKeys.sort(asciiCompare),
  };
}

function evaluateCondition(condition: Condition, values: Record<string, ResolvedValue>): Tri {
  const [operator, operand] = operatorOf(condition);
  if (operator === "all" || operator === "any") {
    const results = (operand as Condition[]).map((child) => evaluateCondition(child, values));
    if (operator === "all") return results.includes("false") ? "false" : results.includes("unknown") ? "unknown" : "true";
    return results.includes("true") ? "true" : results.includes("unknown") ? "unknown" : "false";
  }
  if (operator === "not") {
    const result = evaluateCondition(operand as Condition, values);
    return result === "unknown" ? result : result === "true" ? "false" : "true";
  }
  const comparison = operand as { key: string; value?: unknown; values?: unknown[] };
  const value = values[comparison.key] ?? UNKNOWN;
  if (operator === "is_unknown") return value === UNKNOWN ? "true" : "false";
  if (operator === "is_known") return value === UNKNOWN ? "false" : "true";
  if (value === UNKNOWN) return "unknown";
  if (operator === "eq") return strictEquals(value, comparison.value) ? "true" : "false";
  if (operator === "in") return (comparison.values ?? []).some((item) => strictEquals(value, item)) ? "true" : "false";
  if (typeof value !== "number" || !Number.isInteger(value)) ruleError("invalid_rule_package", "invalid_condition_value", `${operator} requires an integer`);
  return operator === "lt" ? (value < Number(comparison.value) ? "true" : "false") : (value >= Number(comparison.value) ? "true" : "false");
}

function strictEquals(left: unknown, right: unknown): boolean {
  return typeof left === typeof right && left === right;
}

function validTimestamp(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(value) && new Date(value).toISOString() === value;
}

function asciiCompare(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}
