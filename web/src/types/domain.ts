export type InteractionMode = "call_119" | "on_call" | "voice_guidance" | "handover";

export type DataFreshness = "live" | "stale" | "offline" | "unknown";

export type HelperRole = "aed_runner" | "ambulance_greeter";

export type HelperTaskStatus =
  | "offered"
  | "accepted"
  | "en_route"
  | "arrived"
  | "collected"
  | "returning"
  | "delivered"
  | "unavailable"
  | "cancelled"
  | "expired";

export interface Coordinates {
  lat: number;
  lng: number;
  accuracyMeters?: number;
  observedAt?: string;
}
export interface HelperTaskSummary {
  id: string;
  incidentId: string;
  role: HelperRole;
  status: HelperTaskStatus;
  assignmentRevision: number;
  expiresAt: string;
  freshness: DataFreshness;
}

export interface TimelineEvent {
  id: string;
  occurredAt: string;
  label: string;
  source: "user" | "agent" | "rule" | "helper" | "system";
  confirmation: "reported" | "confirmed" | "proposed";
}
