import type { InteractionMode } from "../media/mediaGate";

export type ReviewStatus = "unreviewed_demo" | "in_review" | "reviewed";
export type Confirmation = "proposed" | "reported" | "confirmed";
export type ObservationValue = boolean | number | string;

export interface Observation {
  observationId: string;
  key: string;
  value: ObservationValue;
  source:
    | "button"
    | "voice_report"
    | "dispatcher_report"
    | "camera_proposal"
    | "model_proposal"
    | "system";
  observedAt: string;
  receivedAt?: string;
  confirmation: Confirmation;
  evidenceEventIds?: string[];
}

export interface EvaluationRequest {
  schemaVersion: "1.0.0";
  ruleVersion: string;
  incidentId: string;
  clinicalState: string;
  stateRevision: number;
  interactionMode: InteractionMode;
  modeRevision: number;
  expectedStateRevision?: number | null;
  expectedModeRevision?: number | null;
  trigger: {
    type: "observation" | "timer" | "mode_change" | "resume";
    timerId?: string;
    previousInteractionMode?: InteractionMode;
  };
  observations: Observation[];
  timers: Array<{
    timerId: string;
    status: "running" | "paused" | "stopped";
    remainingMs?: number;
  }>;
}

export interface RenderedTemplate {
  templateId: string;
  kind: "critical_instruction" | "notice";
  locale: string;
  text: string;
  params: Record<string, unknown>;
}

export interface Decision {
  schemaVersion: "1.0.0";
  ruleVersion: string;
  reviewStatus: ReviewStatus;
  interpreterVersion: "1.0";
  incidentId: string;
  trigger: EvaluationRequest["trigger"];
  interactionMode: InteractionMode;
  modeRevision: number;
  guidanceActive: boolean;
  fromState: string;
  toState: string;
  stateChanged: boolean;
  stateRevision: number;
  nextStateRevision: number;
  reasonCode: string;
  acceptedObservationIds: string[];
  rejectedObservations: Array<{
    observationId: string;
    key: string;
    code:
      | "unknown_observation_key"
      | "invalid_value"
      | "source_cannot_confirm"
      | "insufficient_confirmation";
  }>;
  resolvedObservations: Record<string, ObservationValue>;
  unknownObservationKeys: string[];
  conflictingObservationKeys: string[];
  instruction: RenderedTemplate | null;
  notices: RenderedTemplate[];
  actions: Array<{
    kind: string;
    channel: "screen" | "audio";
    params: Record<string, unknown>;
  }>;
  suppressedActions: Array<{
    kind: string;
    channel: "screen" | "audio";
    reason: "audio_not_allowed" | "guidance_suspended";
  }>;
  timerOps: Array<{
    op: "start" | "stop" | "reset" | "pause" | "resume" | "set_audible";
    timerId: string;
    intervalMs: number;
    repeat: boolean;
    audible: boolean;
    reason: "state_entry" | "timer_elapsed" | "mode_policy" | "resume_after_interruption";
  }>;
  outputChannels: Array<"screen" | "audio">;
}

export type Condition = Record<string, unknown>;

export interface TemplateRef {
  templateId: string;
  params?: Record<string, unknown>;
}

export interface RuleAction {
  kind: string;
  params?: Record<string, unknown>;
}

export interface TimerDirective {
  op: Decision["timerOps"][number]["op"];
  timerId: string;
}

export interface RuleOutcome {
  reasonCode: string;
  instruction?: TemplateRef;
}

export interface RuleState {
  id: string;
  kind: "guidance" | "terminal" | "out_of_scope";
  instruction?: TemplateRef;
  actions?: RuleAction[];
  requiredObservations: string[];
  onUnknown: RuleOutcome;
  onUnmatched: RuleOutcome;
  transitions: Array<{
    id: string;
    when: Condition;
    to: string;
    reasonCode: string;
  }>;
  onEnterTimers?: TimerDirective[];
  onTimer?: Array<{
    timerId: string;
    reasonCode: string;
    instruction?: TemplateRef;
    actions?: RuleAction[];
    timerOps?: TimerDirective[];
  }>;
}

export interface RulePackage {
  schemaVersion: "1.0.0";
  ruleVersion: string;
  locale: string;
  reviewStatus: ReviewStatus;
  clinicalReviewRequired: boolean;
  compatibleInterpreterVersions: string[];
  contentHash: string;
  observations: Record<string, {
    key: string;
    type: "boolean" | "integer" | "enum";
    minimumConfirmation: Confirmation;
    values?: string[];
    minimum?: number;
    maximum?: number;
  }>;
  actionChannels: Record<string, "screen" | "audio">;
  timers: Record<string, { id: string; intervalMs: number; repeat: boolean }>;
  timerOrder: string[];
  modePolicies: Record<InteractionMode, {
    audioAllowed: boolean;
    guidanceActive: boolean;
    timerPolicy: "run" | "silent" | "paused";
    noticeTemplateId: string | null;
  }>;
  states: Record<string, RuleState>;
  templates: Record<string, {
    id: string;
    kind: "critical_instruction" | "notice";
    params: string[];
    text: string;
  }>;
  resumeNoticeTemplateId: string | null;
  initialState: string;
}

export interface RulePackageSources {
  flowText: string;
  templatesText: string;
  flowSource?: string;
  templatesSource?: string;
}
