import type { RescueMode } from "./rescue";

export type ApiErrorCode =
  | "unauthorized"
  | "expired"
  | "stale_revision"
  | "rule_mismatch"
  | "unavailable"
  | "invalid_input";

export interface ApiErrorResponse {
  error: { code: ApiErrorCode; message: string; requestId: string; details?: Record<string, unknown> | null };
}

export interface SessionResponse { actorId: string; sessionToken: string; expiresAt: string }
export interface IncidentView {
  incidentId: string; primaryClientId: string; ruleVersion: string; status: "active" | "handed_over" | "closed";
  interactionMode: RescueMode; stateRevision: number; modeRevision: number; snapshotRevision: number;
  authorityEpoch: number; createdAt: string;
}

export interface EventInput {
  eventId: string;
  type: "mode.changed" | "call.reported" | "action.reported" | "event.corrected" | "observation.proposed" | "observation.confirmed" | "command.acknowledged" | "timer.elapsed" | "helper.updated";
  detail: Record<string, unknown>;
  clientId: string; clientInstanceId: string; clientSequence: number; clientTime: string;
  authorityEpoch: number; stateRevision: number; modeRevision: number; ruleVersion: string;
}

export interface EventBatchResponse {
  acknowledgements: Array<{ eventId: string; status: "accepted" | "duplicate" | "conflict"; code?: string | null }>;
  stateRevision: number; modeRevision: number; snapshotRevision: number; authorityEpoch: number;
  lastAcknowledgedClientSequence?: number | null;
}

export interface ObservationInput {
  observationId: string; key: string; value: boolean | number | string | { latitude: number; longitude: number }; source: "voice_report" | "button" | "camera_proposal" | "manual_report";
  observedAt: string; confirmation: "proposed" | "user_confirmed" | "uncertain"; evidenceEventIds: string[];
}

export interface ObservationRecord {
  observationId: string; key: string;
  value: boolean | number | string | { latitude: number; longitude: number };
  source: "user_report" | "button" | "camera_proposal" | "model_proposal" | "geocoder" | "device" | "helper_report" | "rule_engine";
  observedAt: string; confirmation: "unknown" | "proposed" | "reported" | "confirmed";
  evidenceEventIds: string[];
}

export type ObservationValue = ObservationRecord["value"] | null;
export type SnapshotSectionName = "location" | "circumstances" | "patientCondition" | "peoplePresent" | "hazards";
export type SnapshotFreshness = "fresh" | "aging" | "stale" | "unknown";

export interface SnapshotProvenance {
  source: ObservationRecord["source"];
  confirmation: ObservationRecord["confirmation"];
  observedAt: string | null;
  receivedAt: string | null;
  evidenceEventIds: string[];
  correctedFromEventIds: string[];
  observedTimeUncertain: boolean;
}

export interface SnapshotField {
  key: string;
  section: SnapshotSectionName;
  value: ObservationValue;
  provenance: SnapshotProvenance;
  freshness: SnapshotFreshness;
  ageSeconds: number | null;
  pendingProposals: Array<Record<string, unknown>>;
}

export interface ReportedAction {
  action: string;
  reportedAt: string;
  eventId: string;
  source: string;
  detail: Record<string, unknown>;
  correctedFromEventIds: string[];
  retracted: boolean;
}

export interface SceneSnapshotResponse {
  incidentId: string; snapshotRevision: number; generatedThroughRevision: number;
  generatedThroughSequence: number; updatedAt: string | null;
  sections: Record<SnapshotSectionName, SnapshotField[]>;
  actionsPerformed: ReportedAction[];
  observations: ObservationRecord[];
}
export interface AedListResponse { candidates: Array<{ aedId: string; name: string; availability: "available" | "unavailable" | "unknown"; straightLineMeters: number; walkingMeters?: number | null; etaSeconds?: number | null; routeUpdatedAt?: string | null; estimateSource: "route" | "straight_line" | "none" }>; dataUpdatedAt: string | null }
export type ShareScope = "aed_runner" | "ambulance_greeter" | "ems_viewer";
export interface CreateShareResponse { inviteId: string; secret: string; scope: ShareScope; expiresAt: string }
export interface ShareSessionResponse { incidentId: string; scope: ShareScope; helperId: string | null; expiresAt: string }
export interface HelperUpdateResponse { helperId: string; assignmentRevision: number; status: string; locationUpdatedAt: string | null }
export interface HandoffEventsResponse { snapshotRevision: number; generatedThroughRevision: number; events: Array<{ eventId: string; type: string; clientTime: string; serverTime: string; detail: Record<string, unknown> }>; nextCursor: string | null }

export interface RuleEvaluationResponse {
  ruleVersion: string; contentHash: string;
  reviewStatus: "unreviewed_demo" | "in_review" | "reviewed";
  clinicalReviewRequired: boolean; decision: RuleDecision;
}
export interface RuleDecision {
  toState: string; stateChanged: boolean; nextStateRevision: number; reasonCode: string;
  instruction: { templateId: string; kind: "critical_instruction" | "notice"; locale: string; text: string; params: Record<string, unknown> } | null;
  actions: Array<{ kind: string; channel: "screen" | "audio"; params: Record<string, unknown> }>;
  suppressedActions: Array<{ kind: string; channel: "screen" | "audio"; reason: string }>;
  timerOps: Array<Record<string, unknown>>;
  outputChannels: Array<"screen" | "audio">;
}
export interface LiveObservationProposal {
  observationId: string;
  key: "responsive" | "breathing_normal";
  value: boolean | "unknown";
  source: "model_proposal";
  observedAt: string;
  confirmation: "proposed";
  evidenceEventIds: string[];
}
export interface HandoffReadResponse {
  snapshot: Record<string, unknown>; mist: Record<string, unknown>; timeline: Record<string, unknown>;
}
export interface AedAssignmentResponse {
  outcome: "assigned" | "reassigned" | "duplicate_report" | "stale_revision" | "not_assigned" | "aed_mismatch" | "no_candidate" | "conflict";
  incidentId: string; reportId: string | null; helperId: string | null; aedId: string | null;
  assignmentRevision: number | null; previousAedId: string | null;
  excludedAedIds: string[]; deduplicated: boolean; estimate: Record<string, unknown> | null;
}
