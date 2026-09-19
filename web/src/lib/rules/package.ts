import { ruleError } from "./errors";
import { loadRestrictedYaml, normalizeSource } from "./restrictedYaml";
import { schemaIds, validateSchema } from "./schema";
import type {
  Condition,
  RuleAction,
  RulePackage,
  RulePackageSources,
  RuleState,
  TemplateRef,
  TimerDirective,
} from "./types";

export const INTERPRETER_VERSION = "1.0" as const;
const OPERATORS = new Set(["eq", "in", "lt", "gte", "is_unknown", "is_known", "all", "any", "not"]);
const NUMERIC_OPERATORS = new Set(["lt", "gte"]);
const PLACEHOLDER = /\{([a-z][a-z0-9_]*)\}/g;

interface FlowDocument {
  schemaVersion: "1.0.0";
  ruleVersion: string;
  locale: string;
  reviewStatus: RulePackage["reviewStatus"];
  clinicalReviewRequired: boolean;
  compatibleInterpreterVersions: string[];
  resumeNoticeTemplateId: string | null;
  initialState: string;
  observations: Array<RulePackage["observations"][string]>;
  actionKinds: Array<{ id: string; channel: "screen" | "audio" }>;
  timers: Array<{ id: string; intervalMs: number; repeat: boolean }>;
  modePolicies: RulePackage["modePolicies"];
  states: RuleState[];
}

interface TemplatesDocument {
  schemaVersion: "1.0.0";
  ruleVersion: string;
  locale: string;
  reviewStatus: RulePackage["reviewStatus"];
  templates: Array<RulePackage["templates"][string]>;
}

export async function loadRulePackage(sources: RulePackageSources): Promise<RulePackage> {
  const flowSource = sources.flowSource ?? "<flow>";
  const templatesSource = sources.templatesSource ?? "<templates>";
  const flowValue = loadRestrictedYaml(sources.flowText, flowSource);
  const templatesValue = loadRestrictedYaml(sources.templatesText, templatesSource);
  validateSchema(schemaIds.rulePackage, flowValue, flowSource);
  validateSchema(schemaIds.ruleTemplates, templatesValue, templatesSource);

  const flow = flowValue as unknown as FlowDocument;
  const templatesDocument = templatesValue as unknown as TemplatesDocument;
  if (flow.schemaVersion !== "1.0.0" || templatesDocument.schemaVersion !== "1.0.0") {
    ruleError("invalid_rule_package", "unsupported_schema_version", "Unsupported rule schema version");
  }
  if (!flow.compatibleInterpreterVersions.includes(INTERPRETER_VERSION)) {
    ruleError("rule_mismatch", "interpreter_incompatible", `Interpreter ${INTERPRETER_VERSION} is not compatible`);
  }
  for (const field of ["ruleVersion", "locale", "reviewStatus"] as const) {
    if (flow[field] !== templatesDocument[field]) {
      ruleError("invalid_rule_package", "templates_manifest_mismatch", `${templatesSource}: ${field} does not match the flow`);
    }
  }

  requireUnique(flow.observations.map((item) => item.key), "duplicate_observation_key");
  const observations = Object.fromEntries(flow.observations.map((item) => [item.key, item]));
  validateObservationDefinitions(flow);

  requireUnique(flow.actionKinds.map((item) => item.id), "duplicate_action_kind");
  const actionChannels = Object.fromEntries(flow.actionKinds.map((item) => [item.id, item.channel]));
  requireUnique(flow.timers.map((item) => item.id), "duplicate_timer_id");
  const timers = Object.fromEntries(flow.timers.map((item) => [item.id, item]));
  requireUnique(flow.states.map((item) => item.id), "duplicate_state_id");
  const states = Object.fromEntries(flow.states.map((item) => [item.id, item]));
  if (!states[flow.initialState]) {
    ruleError("invalid_rule_package", "unknown_initial_state", `Unknown initial state ${flow.initialState}`);
  }

  requireUnique(templatesDocument.templates.map((item) => item.id), "duplicate_template_id");
  const templates = Object.fromEntries(templatesDocument.templates.map((item) => [item.id, item]));
  validateTemplates(templatesDocument, flow, templates);
  validateStates(flow, observations, states, templates, actionChannels, timers);

  return {
    schemaVersion: flow.schemaVersion,
    ruleVersion: flow.ruleVersion,
    locale: flow.locale,
    reviewStatus: flow.reviewStatus,
    clinicalReviewRequired: flow.clinicalReviewRequired,
    compatibleInterpreterVersions: [...flow.compatibleInterpreterVersions],
    contentHash: await contentHash([
      [flowSource, sources.flowText],
      [templatesSource, sources.templatesText],
    ]),
    observations,
    actionChannels,
    timers,
    timerOrder: flow.timers.map((item) => item.id),
    modePolicies: flow.modePolicies,
    states,
    templates,
    resumeNoticeTemplateId: flow.resumeNoticeTemplateId,
    initialState: flow.initialState,
  };
}

export async function contentHash(parts: Array<[string, string]>): Promise<string> {
  const encoder = new TextEncoder();
  const chunks = parts.flatMap(([name, text]) => [encoder.encode(name), new Uint8Array([0]), encoder.encode(normalizeSource(text)), new Uint8Array([0])]);
  const length = chunks.reduce((total, chunk) => total + chunk.length, 0);
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.length;
  }
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return `sha256:${[...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}

function validateObservationDefinitions(flow: FlowDocument): void {
  for (const definition of flow.observations) {
    if (definition.type === "enum" && !definition.values) packageFailure("invalid_observation_definition", `Enum ${definition.key} has no values`);
    if (definition.type !== "enum" && definition.values) packageFailure("invalid_observation_definition", `Non-enum ${definition.key} has values`);
    if (definition.values?.includes("unknown")) packageFailure("invalid_observation_definition", `${definition.key} reserves unknown`);
    if (definition.type !== "integer" && (definition.minimum !== undefined || definition.maximum !== undefined)) {
      packageFailure("invalid_observation_definition", `${definition.key} has numeric bounds`);
    }
    if (definition.minimum !== undefined && definition.maximum !== undefined && definition.minimum > definition.maximum) {
      packageFailure("invalid_observation_definition", `${definition.key} has inverted bounds`);
    }
  }
}

function validateTemplates(
  document: TemplatesDocument,
  flow: FlowDocument,
  templates: RulePackage["templates"],
): void {
  for (const template of document.templates) {
    const used = new Set([...template.text.matchAll(PLACEHOLDER)].map((match) => match[1]));
    if (!sameSet(used, new Set(template.params))) {
      packageFailure("template_param_mismatch", `Template ${template.id} parameters do not match its text`);
    }
  }
  const refs: Array<["notice" | "critical_instruction", TemplateRef]> = [];
  for (const policy of Object.values(flow.modePolicies)) {
    if (policy.noticeTemplateId) refs.push(["notice", { templateId: policy.noticeTemplateId }]);
  }
  if (flow.resumeNoticeTemplateId) refs.push(["notice", { templateId: flow.resumeNoticeTemplateId }]);
  for (const state of flow.states) {
    if (state.instruction) refs.push(["critical_instruction", state.instruction]);
    for (const outcome of [state.onUnknown, state.onUnmatched]) {
      if (outcome.instruction) refs.push(["critical_instruction", outcome.instruction]);
    }
    for (const timer of state.onTimer ?? []) {
      if (timer.instruction) refs.push(["critical_instruction", timer.instruction]);
    }
  }
  for (const [kind, ref] of refs) validateTemplateRef(ref, kind, templates);
}

function validateStates(
  flow: FlowDocument,
  observations: RulePackage["observations"],
  states: RulePackage["states"],
  templates: RulePackage["templates"],
  actions: RulePackage["actionChannels"],
  timers: RulePackage["timers"],
): void {
  for (const state of flow.states) {
    requireUnique(state.transitions.map((item) => item.id), "duplicate_transition_id");
    if (state.kind === "guidance" && state.transitions.length === 0) packageFailure("guidance_state_has_no_transitions", `${state.id} has no transitions`);
    if (state.kind !== "guidance" && state.transitions.length > 0) packageFailure("terminal_state_has_transitions", `${state.id} has transitions`);

    const referenced = new Set<string>();
    for (const transition of state.transitions) {
      if (!states[transition.to]) packageFailure("dangling_transition_target", `${transition.id} targets ${transition.to}`);
      validateCondition(transition.when, observations, referenced);
    }
    if (!sameSet(referenced, new Set(state.requiredObservations))) {
      packageFailure("required_observations_mismatch", `${state.id} requiredObservations do not match its conditions`);
    }
    for (const action of state.actions ?? []) validateAction(action, actions, templates);
    validateTimerDirectives(state.onEnterTimers ?? [], timers);

    const seenTimers = new Set<string>();
    for (const entry of state.onTimer ?? []) {
      if (!timers[entry.timerId]) packageFailure("unknown_timer_id", `Unknown timer ${entry.timerId}`);
      if (seenTimers.has(entry.timerId)) packageFailure("duplicate_timer_trigger", `Duplicate timer trigger ${entry.timerId}`);
      seenTimers.add(entry.timerId);
      for (const action of entry.actions ?? []) validateAction(action, actions, templates);
      validateTimerDirectives(entry.timerOps ?? [], timers);
    }
  }
}

function validateCondition(
  condition: Condition,
  observations: RulePackage["observations"],
  referenced: Set<string>,
): void {
  const [operator, operand] = operatorOf(condition);
  if (operator === "all" || operator === "any") {
    for (const child of operand as Condition[]) validateCondition(child, observations, referenced);
    return;
  }
  if (operator === "not") {
    validateCondition(operand as Condition, observations, referenced);
    return;
  }
  const comparison = operand as { key: string; value?: unknown; values?: unknown[] };
  const definition = observations[comparison.key];
  if (!definition) packageFailure("unknown_observation_key", `Unknown observation ${comparison.key}`);
  referenced.add(comparison.key);
  if (NUMERIC_OPERATORS.has(operator) && definition.type !== "integer") packageFailure("invalid_condition_value", `${operator} requires an integer observation`);
  if (operator === "eq" && !accepts(definition, comparison.value)) packageFailure("invalid_condition_value", `Invalid comparison value for ${comparison.key}`);
  if (operator === "in" && !(comparison.values ?? []).every((value) => accepts(definition, value))) packageFailure("invalid_condition_value", `Invalid list value for ${comparison.key}`);
}

export function operatorOf(condition: Condition): [string, unknown] {
  const entries = Object.entries(condition);
  if (entries.length !== 1) packageFailure("invalid_condition", "A condition must have exactly one operator");
  const entry = entries[0];
  if (!entry || !OPERATORS.has(entry[0])) packageFailure("unknown_operator", `Unknown condition operator ${entry?.[0] ?? ""}`);
  return entry;
}

export function accepts(definition: RulePackage["observations"][string], value: unknown): boolean {
  if (definition.type === "boolean") return typeof value === "boolean";
  if (definition.type === "integer") {
    return Number.isInteger(value) && typeof value === "number" &&
      (definition.minimum === undefined || value >= definition.minimum) &&
      (definition.maximum === undefined || value <= definition.maximum);
  }
  return typeof value === "string" && (definition.values ?? []).includes(value);
}

function validateTemplateRef(ref: TemplateRef, kind: "notice" | "critical_instruction", templates: RulePackage["templates"]): void {
  const template = templates[ref.templateId];
  if (!template) packageFailure("unknown_template_id", `Unknown template ${ref.templateId}`);
  if (template.kind !== kind) packageFailure("template_kind_mismatch", `${ref.templateId} is not a ${kind}`);
  if (!sameSet(new Set(Object.keys(ref.params ?? {})), new Set(template.params))) packageFailure("template_param_mismatch", `${ref.templateId} parameters do not match`);
}

function validateAction(action: RuleAction, actions: RulePackage["actionChannels"], templates: RulePackage["templates"]): void {
  if (!actions[action.kind]) packageFailure("unknown_action_kind", `Unknown action ${action.kind}`);
  const templateId = action.params?.template_id;
  if (typeof templateId === "string" && !templates[templateId]) packageFailure("unknown_template_id", `Unknown template ${templateId}`);
}

function validateTimerDirectives(directives: TimerDirective[], timers: RulePackage["timers"]): void {
  for (const directive of directives) {
    if (!timers[directive.timerId]) packageFailure("unknown_timer_id", `Unknown timer ${directive.timerId}`);
  }
}

function requireUnique(values: string[], detail: string): void {
  if (new Set(values).size !== values.length) packageFailure(detail, `Duplicate value in ${detail}`);
}

function sameSet<T>(left: Set<T>, right: Set<T>): boolean {
  return left.size === right.size && [...left].every((item) => right.has(item));
}

function packageFailure(detail: string, message: string): never {
  return ruleError("invalid_rule_package", detail, message);
}
