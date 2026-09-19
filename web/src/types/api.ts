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
  observationId: string; key: string; value: boolean | number | string; source: "voice_report" | "button" | "camera_proposal" | "manual_report";
  observedAt: string; confirmation: "proposed" | "user_confirmed" | "uncertain"; evidenceEventIds: string[];
}

export interface SceneSnapshotResponse { incidentId: string; snapshotRevision: number; generatedThroughRevision: number; observations: ObservationInput[] }
export interface AedListResponse { candidates: Array<{ aedId: string; name: string; availability: "available" | "unavailable" | "unknown"; straightLineMeters: number; walkingMeters?: number | null; etaSeconds?: number | null; routeUpdatedAt?: string | null; estimateSource: "route" | "straight_line" | "none" }>; dataUpdatedAt: string | null }
export type ShareScope = "aed_runner" | "ambulance_greeter" | "ems_viewer";
export interface CreateShareResponse { inviteId: string; secret: string; scope: ShareScope; expiresAt: string }
export interface ShareSessionResponse { incidentId: string; scope: ShareScope; helperId: string | null; expiresAt: string }
export interface HelperUpdateResponse { helperId: string; assignmentRevision: number; status: string; locationUpdatedAt: string | null }
export interface HandoffEventsResponse { snapshotRevision: number; generatedThroughRevision: number; events: Array<{ eventId: string; type: string; clientTime: string; serverTime: string; detail: Record<string, unknown> }>; nextCursor: string | null }
