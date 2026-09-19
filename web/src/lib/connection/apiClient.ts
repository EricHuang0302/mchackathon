import type {
  AedListResponse, ApiErrorResponse, CreateShareResponse, EventBatchResponse, EventInput,
  HandoffEventsResponse, HelperUpdateResponse, IncidentView, ObservationInput, SceneSnapshotResponse,
  SessionResponse, ShareScope, ShareSessionResponse,
} from "../../types/api";

export class ApiClientError extends Error {
  constructor(public readonly status: number, public readonly payload: ApiErrorResponse) {
    super(payload.error.message);
  }
  get code() { return this.payload.error.code }
}

export const userMessageForApiError = (error: unknown) => {
  if (!(error instanceof ApiClientError)) return "目前無法連線服務，操作會保留在本機。";
  if (error.status === 401) return "登入已失效，請重新開始救援流程。";
  if (error.status === 403) return "你沒有權限查看或修改這次救援。";
  if (error.status === 409) return "資料版本已更新，請重新同步後再試。";
  if (error.status === 503) return "此功能目前無法使用，資料會保留在本機。";
  return "輸入資料無法處理，請確認後再試。";
};

export class ApiClient {
  constructor(private readonly token?: string, private readonly fetcher: typeof fetch = fetch) {}

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    if (init.body) headers.set("Content-Type", "application/json");
    if (this.token) headers.set("Authorization", `Bearer ${this.token}`);
    let response: Response;
    try { response = await this.fetcher(path, { ...init, headers }); }
    catch { throw new ApiClientError(503, { error: { code: "unavailable", message: "Network unavailable", requestId: crypto.randomUUID() } }); }
    const body = await response.json().catch(() => null) as T | ApiErrorResponse | null;
    if (!response.ok) {
      const fallback: ApiErrorResponse = { error: { code: response.status === 503 ? "unavailable" : "invalid_input", message: response.statusText || "Request failed", requestId: crypto.randomUUID() } };
      throw new ApiClientError(response.status, (body as ApiErrorResponse | null) ?? fallback);
    }
    return body as T;
  }

  createSession() { return this.request<SessionResponse>("/v1/sessions", { method: "POST" }); }
  createIncident(body: { incidentId: string; primaryClientId: string; ruleVersion: string }) { return this.request<IncidentView>("/v1/incidents", { method: "POST", body: JSON.stringify(body) }); }
  uploadEvents(id: string, events: EventInput[]) { return this.request<EventBatchResponse>(`/v1/incidents/${id}/event-batches`, { method: "POST", body: JSON.stringify({ events }) }); }
  addObservations(id: string, body: { observations: ObservationInput[]; expectedSnapshotRevision: number; idempotencyKey: string }) { return this.request<{ snapshotRevision: number; acceptedObservationIds: string[]; generatedThroughRevision: number }>(`/v1/incidents/${id}/scene-observations`, { method: "POST", body: JSON.stringify(body) }); }
  getSnapshot(id: string) { return this.request<SceneSnapshotResponse>(`/v1/incidents/${id}/snapshot`); }
  describeLocation(id: string, body: { lat: number; lng: number; accuracyMeters?: number }) { return this.request<{ candidates: unknown[] }>(`/v1/incidents/${id}/location-descriptions`, { method: "POST", body: JSON.stringify(body) }); }
  createShare(id: string, body: { scope: ShareScope; helperId?: string; expiresInSeconds: number; idempotencyKey: string }) { return this.request<CreateShareResponse>(`/v1/incidents/${id}/shares`, { method: "POST", body: JSON.stringify(body) }); }
  redeemShare(secret: string) { return this.request<ShareSessionResponse>("/v1/share-sessions", { method: "POST", body: JSON.stringify({ secret }) }); }
  updateHelper(id: string, helperId: string, body: { updateId: string; expectedAssignmentRevision: number; status?: "accepted" | "en_route" | "arrived" | "obtained" | "unavailable"; lat?: number; lng?: number; locationAccuracyMeters?: number; reportedAt: string }) { return this.request<HelperUpdateResponse>(`/v1/incidents/${id}/helpers/${helperId}/updates`, { method: "POST", body: JSON.stringify(body) }); }
  getAeds(id: string, limit = 10) { return this.request<AedListResponse>(`/v1/incidents/${id}/aeds?limit=${limit}`); }
  getHandoffEvents(id: string, cursor?: string, limit = 25) { const query = new URLSearchParams({ limit: String(limit) }); if (cursor) query.set("cursor", cursor); return this.request<HandoffEventsResponse>(`/v1/incidents/${id}/handoff/events?${query}`); }
  revokeAccess(id: string, expectedStateRevision: number, idempotencyKey = crypto.randomUUID()) { return this.request<{ stateRevision: number; revokedInvitations: number; revokedGrants: number }>(`/v1/incidents/${id}/access-revocations`, { method: "POST", body: JSON.stringify({ expectedStateRevision, idempotencyKey }) }); }
  patchIncident(id: string, status: "handed_over" | "closed", expectedStateRevision: number) { return this.request<IncidentView>(`/v1/incidents/${id}`, { method: "PATCH", body: JSON.stringify({ status, expectedStateRevision }) }); }
}
