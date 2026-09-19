import type {
  AedListResponse, ApiErrorResponse, CreateShareResponse, EventBatchResponse, EventInput,
  HandoffEventsResponse, HelperUpdateResponse, IncidentView, ObservationInput, SceneSnapshotResponse,
  SessionResponse, ShareScope, ShareSessionResponse, RuleEvaluationResponse,
  HandoffReadResponse, AedAssignmentReadResponse, AedAssignmentResponse,
  SceneImageAnalysisResponse,
} from "../../types/api";
import { ApiError, RestClient } from "./restClient";

export class ApiClientError extends Error {
  constructor(public readonly status: number, public readonly payload: ApiErrorResponse) {
    super(payload.error.message);
  }
  get code() { return this.payload.error.code }
}

export const userMessageForApiError = (error: unknown) => {
  if (!(error instanceof ApiClientError)) return "目前無法連線服務，操作會保留在本機。";
  if (error.status === 401) return "登入已失效，請重新開始救援流程。";
  if (error.code === "expired") return "邀請已過期、已使用，或救援流程已結束。";
  if (error.status === 403) return "你沒有權限查看或修改這次救援。";
  if (error.status === 409) return "資料版本已更新，請重新同步後再試。";
  if (error.status === 503) return "此功能目前無法使用，資料會保留在本機。";
  return "輸入資料無法處理，請確認後再試。";
};

export class ApiClient {
  readonly #client: RestClient;

  constructor(
    token?: string,
    fetcher: typeof fetch = globalThis.fetch.bind(globalThis),
  ) {
    this.#client = new RestClient({
      baseUrl: "",
      getToken: async () => token ?? null,
      fetchImpl: fetcher,
    });
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    try {
      return await this.#client.request<T>(init.method ?? "GET", path, {
        body: init.body ? JSON.parse(String(init.body)) : undefined,
        signal: init.signal ?? undefined,
      });
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      throw new ApiClientError(error.status || 503, {
        error: {
          code: error.code === "unknown" ? "unavailable" : error.code,
          message: error.message,
          requestId: crypto.randomUUID(),
          details: error.details as Record<string, unknown> | undefined,
        },
      });
    }
  }

  createSession() { return this.request<SessionResponse>("/v1/sessions", { method: "POST" }); }
  createIncident(body: { incidentId: string; primaryClientId: string; ruleVersion: string }) { return this.request<IncidentView>("/v1/incidents", { method: "POST", body: JSON.stringify(body) }); }
  uploadEvents(id: string, events: EventInput[]) { return this.request<EventBatchResponse>(`/v1/incidents/${id}/event-batches`, { method: "POST", body: JSON.stringify({ events }) }); }
  addObservations(id: string, body: { observations: ObservationInput[]; expectedSnapshotRevision: number; idempotencyKey: string }) { return this.request<{ snapshotRevision: number; acceptedObservationIds: string[]; generatedThroughRevision: number }>(`/v1/incidents/${id}/scene-observations`, { method: "POST", body: JSON.stringify(body) }); }
  analyzeSceneImage(id: string, body: { imageBase64: string; mimeType: "image/jpeg" | "image/webp"; capturedAt: string; expectedModeRevision: number }) { return this.request<SceneImageAnalysisResponse>(`/v1/incidents/${id}/scene-image-analyses`, { method: "POST", body: JSON.stringify(body) }); }
  getSnapshot(id: string) { return this.request<SceneSnapshotResponse>(`/v1/incidents/${id}/snapshot`); }
  describeLocation(id: string, body: { lat: number; lng: number; accuracyMeters?: number }) { return this.request<{ candidates: unknown[] }>(`/v1/incidents/${id}/location-descriptions`, { method: "POST", body: JSON.stringify(body) }); }
  createShare(id: string, body: { scope: ShareScope; helperId?: string; expiresInSeconds: number; idempotencyKey: string }) { return this.request<CreateShareResponse>(`/v1/incidents/${id}/shares`, { method: "POST", body: JSON.stringify(body) }); }
  redeemShare(secret: string) { return this.request<ShareSessionResponse>("/v1/share-sessions", { method: "POST", body: JSON.stringify({ secret }) }); }
  updateHelper(id: string, helperId: string, body: { updateId: string; expectedAssignmentRevision: number; status?: "accepted" | "en_route" | "arrived" | "obtained" | "delivered" | "unavailable"; lat?: number; lng?: number; locationAccuracyMeters?: number; reportedAt: string }) { return this.request<HelperUpdateResponse>(`/v1/incidents/${id}/helpers/${helperId}/updates`, { method: "POST", body: JSON.stringify(body) }); }
  getAeds(id: string, limit = 10, location?: { lat: number; lng: number }) {
    const query = new URLSearchParams({ limit: String(limit) });
    if (location) { query.set("lat", String(location.lat)); query.set("lng", String(location.lng)); }
    return this.request<AedListResponse>(`/v1/incidents/${id}/aeds?${query}`);
  }
  getHandoffEvents(id: string, cursor?: string, limit = 25) { const query = new URLSearchParams({ limit: String(limit) }); if (cursor) query.set("cursor", cursor); return this.request<HandoffEventsResponse>(`/v1/incidents/${id}/handoff/events?${query}`); }
  evaluateRules(id: string, body: { expectedStateRevision: number; expectedModeRevision: number; trigger: Record<string, unknown>; observations: Array<Record<string, unknown>>; timers: Array<Record<string, unknown>> }) {
    return this.request<RuleEvaluationResponse>(`/v1/incidents/${id}/rule-evaluations`, { method: "POST", body: JSON.stringify(body) });
  }
  getHandoff(id: string, cursor?: string, limit = 25) {
    const query = new URLSearchParams({ limit: String(limit) });
    if (cursor) query.set("cursor", cursor);
    return this.request<HandoffReadResponse>(`/v1/incidents/${id}/handoff?${query}`);
  }
  dispatchAed(id: string, body: { helperId: string; expectedStateRevision: number; helperLocation?: { latitude: number; longitude: number } }) {
    return this.request<AedAssignmentResponse>(`/v1/incidents/${id}/aed-assignments`, { method: "POST", body: JSON.stringify(body) });
  }
  getAedAssignment(id: string, helperId: string) {
    return this.request<AedAssignmentReadResponse>(`/v1/incidents/${id}/helpers/${helperId}/aed-assignment`);
  }
  reportAedUnavailable(id: string, helperId: string, body: { reportId: string; aedId: string; reasonCode: string; expectedAssignmentRevision: number; reportedAt: string; helperLocation?: { latitude: number; longitude: number } }) {
    return this.request<AedAssignmentResponse>(`/v1/incidents/${id}/helpers/${helperId}/aed-unavailability-reports`, { method: "POST", body: JSON.stringify(body) });
  }
  revokeAccess(id: string, expectedStateRevision: number, idempotencyKey = crypto.randomUUID()) { return this.request<{ stateRevision: number; revokedInvitations: number; revokedGrants: number }>(`/v1/incidents/${id}/access-revocations`, { method: "POST", body: JSON.stringify({ expectedStateRevision, idempotencyKey }) }); }
  patchIncident(id: string, status: "handed_over" | "closed", expectedStateRevision: number) { return this.request<IncidentView>(`/v1/incidents/${id}`, { method: "PATCH", body: JSON.stringify({ status, expectedStateRevision }) }); }
}
