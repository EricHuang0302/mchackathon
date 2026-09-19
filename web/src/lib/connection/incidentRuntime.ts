import type { EventInput, IncidentView } from "../../types/api";
import type { ShareScope } from "../../types/api";
import type { RescueMode } from "../../types/rescue";
import { audioGate } from "../media/audioGate";
import { ApiClient, userMessageForApiError } from "./apiClient";
import { clearIncidentSession, getOrCreateSession, getPrimaryIdentity, type PrimaryIdentity } from "./session";
import { LiveClient } from "./liveClient";

type ModeReason = "dial_started" | "dispatcher_reported_active" | "user_reports_call_failed" | "user_reports_call_ended_or_failed" | "user_reports_ems_arrived";
type PendingEvent = { eventId: string; type: EventInput["type"]; detail: Record<string, unknown>; clientTime: string; targetMode?: RescueMode; prepared?: EventInput };
export interface IntegrationStatus { phase: "idle" | "connecting" | "ready" | "syncing" | "offline" | "error"; message: string; incidentId?: string; stateRevision?: number; modeRevision?: number; snapshotRevision?: number; aedDataAvailable?: boolean }

const queueKey = "first-aid.primary.outbox.v1";
const readQueue = (): PendingEvent[] => { try { return JSON.parse(sessionStorage.getItem(queueKey) ?? "[]") as PendingEvent[]; } catch { return []; } };
const saveQueue = (queue: PendingEvent[]) => { try { sessionStorage.setItem(queueKey, JSON.stringify(queue)); } catch { /* Visible through sync status on next request. */ } };

export class IncidentRuntime {
  private api: ApiClient | null = null;
  private identity: PrimaryIdentity | null = null;
  private view: IncidentView | null = null;
  private live: LiveClient | null = null;
  private queue: PendingEvent[] = typeof sessionStorage === "undefined" ? [] : readQueue();
  private sequence = this.queue.reduce((maximum, item) => Math.max(maximum, item.prepared?.clientSequence ?? 0), 0);
  private flushing = false;
  private onStatus: (status: IntegrationStatus) => void = () => undefined;
  private started = false;

  configure(onStatus: (status: IntegrationStatus) => void) { this.onStatus = onStatus; }
  async start() {
    if (this.started) return;
    this.started = true;
    this.onStatus({ phase: "connecting", message: "正在建立本機救援連線…" });
    try {
      const session = await getOrCreateSession("primary");
      this.identity = getPrimaryIdentity();
      this.api = new ApiClient(session.sessionToken);
      this.view = await this.api.createIncident({ incidentId: this.identity.incidentId, primaryClientId: this.identity.clientId, ruleVersion: this.identity.ruleVersion });
      this.onStatus({ phase: "ready", message: "本機 API 已連線", incidentId: this.view.incidentId, stateRevision: this.view.stateRevision, modeRevision: this.view.modeRevision, snapshotRevision: this.view.snapshotRevision });
      this.live = new LiveClient(session, this.identity, this.view, (message) => this.onStatus({ phase: message.startsWith("live_error") ? "error" : "ready", message, incidentId: this.view?.incidentId, stateRevision: this.view?.stateRevision, modeRevision: this.view?.modeRevision, snapshotRevision: this.view?.snapshotRevision }));
      this.live.connect();
      const [snapshot, aeds] = await Promise.all([this.api.getSnapshot(this.view.incidentId), this.api.getAeds(this.view.incidentId)]);
      this.view.snapshotRevision = snapshot.snapshotRevision;
      this.onStatus({ phase: "ready", message: aeds.candidates.length ? "本機 API 與 AED 資料已連線" : "本機 API 已連線；AED 真實資料尚未載入", incidentId: this.view.incidentId, stateRevision: this.view.stateRevision, modeRevision: this.view.modeRevision, snapshotRevision: snapshot.snapshotRevision, aedDataAvailable: aeds.candidates.length > 0 });
      await this.flush();
    } catch (error) {
      this.started = false;
      this.onStatus({ phase: navigator.onLine ? "error" : "offline", message: userMessageForApiError(error) });
    }
  }
  enqueueMode(targetMode: RescueMode, reason: ModeReason) { this.enqueue("mode.changed", { interactionMode: targetMode, reason }, targetMode); if (targetMode === "on_call" || targetMode === "handover") this.live?.silence(); }
  enqueueAction(action: string, eventId: string = crypto.randomUUID()) { this.enqueue("action.reported", { action }, undefined, eventId); }
  private enqueue(type: EventInput["type"], detail: Record<string, unknown>, targetMode?: RescueMode, eventId: string = crypto.randomUUID()) {
    if (this.queue.some((item) => item.eventId === eventId)) return;
    this.queue.push({ eventId, type, detail, targetMode, clientTime: new Date().toISOString() });
    saveQueue(this.queue);
    void this.flush();
  }
  private async flush() {
    if (this.flushing || !this.api || !this.identity || !this.view || !navigator.onLine) return;
    this.flushing = true;
    try {
      while (this.queue.length) {
        const pending = this.queue[0]!;
        this.onStatus({ phase: "syncing", message: "正在同步救援紀錄…", incidentId: this.view.incidentId, stateRevision: this.view.stateRevision, modeRevision: this.view.modeRevision, snapshotRevision: this.view.snapshotRevision });
        const nextModeRevision = pending.type === "mode.changed" ? this.view.modeRevision + 1 : this.view.modeRevision;
        const event: EventInput = pending.prepared ?? { eventId: pending.eventId, type: pending.type, detail: pending.detail, clientId: this.identity.clientId, clientInstanceId: this.identity.clientInstanceId, clientSequence: ++this.sequence, clientTime: pending.clientTime, authorityEpoch: this.view.authorityEpoch, stateRevision: this.view.stateRevision, modeRevision: nextModeRevision, ruleVersion: this.identity.ruleVersion };
        if (!pending.prepared) { pending.prepared = event; saveQueue(this.queue); }
        const result = await this.api.uploadEvents(this.view.incidentId, [event]);
        const ack = result.acknowledgements[0]!;
        this.view = { ...this.view, stateRevision: result.stateRevision, modeRevision: result.modeRevision, snapshotRevision: result.snapshotRevision, authorityEpoch: result.authorityEpoch, interactionMode: pending.targetMode ?? this.view.interactionMode };
        this.live?.update(this.view);
        if (ack.status === "conflict" || ack.code) { this.onStatus({ phase: "error", message: ack.code === "stale_revision" ? "伺服器版本較新，已停止自動重送，請重新開始流程。" : "事件同步衝突，紀錄仍保留在本機。", incidentId: this.view.incidentId, stateRevision: this.view.stateRevision, modeRevision: this.view.modeRevision, snapshotRevision: this.view.snapshotRevision }); break; }
        this.queue.shift(); saveQueue(this.queue);
        if (pending.targetMode === "voice_guidance" && audioGate.isResumeRequested()) this.live?.requestResume();
      }
      if (!this.queue.length) this.onStatus({ phase: "ready", message: "救援紀錄已同步", incidentId: this.view.incidentId, stateRevision: this.view.stateRevision, modeRevision: this.view.modeRevision, snapshotRevision: this.view.snapshotRevision });
    } catch (error) { this.onStatus({ phase: navigator.onLine ? "error" : "offline", message: userMessageForApiError(error), incidentId: this.view?.incidentId }); }
    finally { this.flushing = false; }
  }
  onOnline() { void this.start().then(() => this.flush()); }
  onHidden() { this.live?.silence(); }
  async createShare(scope: ShareScope) {
    if (!this.api || !this.view) throw new Error("Incident is not connected");
    const helperId = scope === "ems_viewer" ? undefined : crypto.randomUUID();
    const share = await this.api.createShare(this.view.incidentId, { scope, helperId, expiresInSeconds: 300, idempotencyKey: crypto.randomUUID() });
    return `${location.origin}/join/${share.inviteId}#${share.secret}`;
  }
  async addObservation(key: string, value: string) {
    if (!this.api || !this.view) return;
    try {
      const result = await this.api.addObservations(this.view.incidentId, {
        expectedSnapshotRevision: this.view.snapshotRevision,
        idempotencyKey: crypto.randomUUID(),
        observations: [{ observationId: crypto.randomUUID(), key, value, source: "button", observedAt: new Date().toISOString(), confirmation: "uncertain", evidenceEventIds: [] }],
      });
      this.view.snapshotRevision = result.snapshotRevision;
      this.live?.update(this.view);
    } catch (error) { this.onStatus({ phase: "error", message: userMessageForApiError(error), incidentId: this.view.incidentId, stateRevision: this.view.stateRevision, modeRevision: this.view.modeRevision, snapshotRevision: this.view.snapshotRevision }); }
  }
  async resetIncident() {
    const api = this.api; const view = this.view;
    this.live?.close();
    if (api && view && navigator.onLine) {
      try { const revoked = await api.revokeAccess(view.incidentId, view.stateRevision); view.stateRevision = revoked.stateRevision; await api.patchIncident(view.incidentId, "closed", view.stateRevision); } catch { /* Local reset remains available when remote close fails. */ }
    }
    this.queue = []; this.sequence = 0; saveQueue([]); clearIncidentSession(); this.api = null; this.identity = null; this.view = null; this.started = false;
    this.onStatus({ phase: "idle", message: "已準備新的救援流程" });
  }
}

export const incidentRuntime = new IncidentRuntime();
