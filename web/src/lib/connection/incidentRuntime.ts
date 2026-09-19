import type { IncidentView, SessionResponse, ShareScope } from "../../types/api";
import type { RescueMode } from "../../types/rescue";
import { BrowserMicrophone } from "../media/microphone";
import { MediaGate } from "../media/mediaGate";
import { bytesToBase64, Pcm16Encoder } from "../media/pcm16";
import { BrowserPcmPlayback } from "../media/pcmPlayback";
import { RuntimeLifecycle } from "../offline/runtimeLifecycle";
import { RuntimeStore, type RuntimeIncident } from "../offline/runtimeStore";
import { ApiClient, userMessageForApiError } from "./apiClient";
import { EventBatchSync, type EventBatchEvent } from "./eventBatchSync";
import { LiveSocket, type LiveEnvelope, type LiveServerMessage } from "./liveSocket";
import { RestClient } from "./restClient";
import {
  clearIncidentSession,
  getOrCreateSession,
  getPrimaryIdentity,
  type PrimaryIdentity,
} from "./session";

type ModeReason =
  | "dial_started"
  | "dispatcher_reported_active"
  | "user_reports_call_failed"
  | "user_reports_call_ended_or_failed"
  | "user_reports_ems_arrived";

export type IntegrationPhase =
  | "initializing"
  | "offline"
  | "syncing"
  | "online"
  | "resyncing"
  | "degraded";

export interface IntegrationStatus {
  phase: IntegrationPhase;
  message: string;
  incidentId?: string;
  interactionMode?: RescueMode;
  stateRevision?: number;
  modeRevision?: number;
  snapshotRevision?: number;
  aedDataAvailable?: boolean;
}

type PendingReport =
  | { type: "mode.changed"; detail: { interactionMode: RescueMode; reason: ModeReason } }
  | { type: "action.reported"; detail: { action: string }; eventId?: string };

const INCIDENT_LIFETIME_MS = 72 * 60 * 60 * 1_000;

export class IncidentRuntime {
  readonly #playback = new BrowserPcmPlayback();
  readonly #microphone = new BrowserMicrophone();
  readonly #mediaGate = new MediaGate(this.#playback, this.#microphone, {
    stop: () => undefined,
  });
  readonly #pendingReports: PendingReport[] = [];
  #reportQueue: Promise<void> = Promise.resolve();
  #api: ApiClient | null = null;
  #identity: PrimaryIdentity | null = null;
  #session: SessionResponse | null = null;
  #incident: RuntimeIncident | null = null;
  #store: RuntimeStore | null = null;
  #sync: EventBatchSync | null = null;
  #live: LiveSocket | null = null;
  #lifecycle: RuntimeLifecycle | null = null;
  #encoder: Pcm16Encoder | null = null;
  #mediaSequence = 0;
  #liveSequence = 0;
  #starting: Promise<void> | null = null;
  #demoMode = false;
  #resumeRequested = false;
  #onStatus: (status: IntegrationStatus) => void = () => undefined;

  configure(
    onStatus: (status: IntegrationStatus) => void,
    options: { demoMode?: boolean } = {},
  ): void {
    this.#onStatus = onStatus;
    this.#demoMode = options.demoMode ?? false;
  }

  initialize(): Promise<void> {
    if (this.#demoMode || this.#sync) return Promise.resolve();
    this.#starting ??= this.#initialize().finally(() => {
      this.#starting = null;
    });
    return this.#starting;
  }

  start(): Promise<void> {
    return this.initialize();
  }

  reportModeChange(targetMode: RescueMode, reason: ModeReason): void {
    if (this.#demoMode) return;
    if (targetMode !== "voice_guidance") this.suspend();
    const report: PendingReport = {
      type: "mode.changed",
      detail: { interactionMode: targetMode, reason },
    };
    if (!this.#incident) {
      this.#pendingReports.push(report);
      void this.initialize();
      return;
    }
    void this.#queueReport(report);
  }

  enqueueMode(targetMode: RescueMode, reason: ModeReason): void {
    this.reportModeChange(targetMode, reason);
  }

  async reportAction(action: string, eventId: string = crypto.randomUUID()): Promise<void> {
    if (this.#demoMode) return;
    const report: PendingReport = {
      type: "action.reported",
      detail: { action },
      eventId,
    };
    if (!this.#incident) {
      this.#pendingReports.push(report);
      await this.initialize();
      return;
    }
    await this.#queueReport(report);
  }

  enqueueAction(action: string, eventId: string = crypto.randomUUID()): void {
    void this.reportAction(action, eventId);
  }

  resumeGuidance(): void {
    this.#resumeRequested = true;
    void this.#playback.enable().catch((error) => {
      this.#emit("degraded", permissionMessage(error));
    });
    void this.#flush().then(() => {
      if (
        this.#incident?.interactionMode === "voice_guidance" &&
        this.#sync?.state === "idle"
      ) {
        this.#live?.sendControl(this.#envelope({ type: "resume.request" }));
      }
    });
  }

  suspend(): void {
    this.#resumeRequested = false;
    this.#encoder?.reset();
    this.#mediaGate.stopAll();
    if (this.#live?.state === "online") {
      this.#live.sendControl(this.#envelope({ type: "mode.silence" }));
    }
  }

  onOnline(): void {
    if (this.#demoMode) return;
    void this.initialize().then(() => {
      return this.#flush();
    }).then(() => {
      if (this.#sync?.state === "idle") this.#live?.connect();
    });
  }

  onHidden(): void {
    this.suspend();
  }

  async createShare(scope: ShareScope) {
    if (!this.#api || !this.#incident) throw new Error("Incident is not connected");
    const helperId = scope === "ems_viewer" ? undefined : crypto.randomUUID();
    const share = await this.#api.createShare(this.#incident.incidentId, {
      scope,
      helperId,
      expiresInSeconds: 300,
      idempotencyKey: crypto.randomUUID(),
    });
    return share;
  }

  async addObservation(key: string, value: string): Promise<void> {
    if (!this.#api || !this.#incident) return;
    try {
      const result = await this.#api.addObservations(this.#incident.incidentId, {
        expectedSnapshotRevision: this.#incident.snapshotRevision ?? 0,
        idempotencyKey: crypto.randomUUID(),
        observations: [{
          observationId: crypto.randomUUID(),
          key,
          value,
          source: "button",
          observedAt: new Date().toISOString(),
          confirmation: "uncertain",
          evidenceEventIds: [],
        }],
      });
      this.#incident.snapshotRevision = result.snapshotRevision;
      await this.#store?.saveIncident(this.#incident);
      this.#emit("online", "現場觀察已同步");
    } catch (error) {
      this.#emit(navigator.onLine ? "degraded" : "offline", userMessageForApiError(error));
    }
  }

  async resetIncident(): Promise<void> {
    const api = this.#api;
    const incident = this.#incident;
    this.suspend();
    this.#live?.disconnect();
    if (api && incident && navigator.onLine) {
      try {
        const revoked = await api.revokeAccess(
          incident.incidentId,
          incident.stateRevision ?? 0,
        );
        await api.patchIncident(incident.incidentId, "closed", revoked.stateRevision);
      } catch {
        // Local reset remains available if the API is unavailable.
      }
    }
    await this.dispose();
    clearIncidentSession();
    this.#emit("initializing", "已準備新的救援流程");
  }

  async dispose(): Promise<void> {
    await this.#reportQueue.catch(() => undefined);
    this.#lifecycle?.stop();
    this.#lifecycle = null;
    this.#live?.disconnect();
    this.#live = null;
    this.#sync?.pause();
    this.#sync = null;
    this.#mediaGate.stopAll();
    await this.#store?.close();
    this.#store = null;
    this.#incident = null;
    this.#identity = null;
    this.#session = null;
    this.#api = null;
    this.#reportQueue = Promise.resolve();
  }

  async #initialize(): Promise<void> {
    this.#emit("initializing", "正在建立本機救援連線…");
    try {
      this.#store ??= new RuntimeStore();
      await this.#store.purgeExpired();
      this.#identity ??= getPrimaryIdentity();
      const restored = await this.#store.loadIncident(this.#identity.incidentId);
      this.#incident ??= restored ?? provisionalIncident(this.#identity);
      this.#incident = { ...this.#incident, guidancePaused: true };
      await this.#store.saveIncident(this.#incident);
      this.#applyPausedPolicy();
      this.#store.subscribeStatus((status) => {
        if (status === "degraded") this.#emit("degraded", "裝置儲存空間目前不可用");
      });
      if (!this.#lifecycle) this.#createLifecycle();

      while (this.#pendingReports.length > 0) {
        await this.#queueReport(this.#pendingReports.shift()!);
      }

      this.#session = await getOrCreateSession("primary");
      this.#api = new ApiClient(this.#session.sessionToken);
      const serverView = await this.#api.createIncident({
        incidentId: this.#identity.incidentId,
        primaryClientId: this.#identity.clientId,
        ruleVersion: this.#identity.ruleVersion,
      });
      this.#incident = reconcileIncident(this.#incident, serverView);
      await this.#store.saveIncident(this.#incident);
      this.#applyPausedPolicy();

      const rest = new RestClient({
        baseUrl: "",
        getToken: async () => this.#session?.sessionToken ?? null,
      });
      this.#sync = new EventBatchSync(rest, this.#store);
      this.#sync.subscribeState((state) => {
        if (state === "syncing") this.#emit("syncing", "正在同步救援紀錄…");
        if (state === "resyncing") this.#emit("resyncing", "資料版本衝突，紀錄仍保留在此裝置");
        if (state === "error") this.#emit(navigator.onLine ? "degraded" : "offline", "同步中斷，紀錄仍保留在此裝置");
      });
      this.#createLiveSocket();
      this.#emit(navigator.onLine ? "online" : "offline", navigator.onLine ? "本機 API 已連線" : "目前離線，操作會保留在此裝置");
      await this.#flush();
      if (this.#sync.state === "idle") this.#live?.connect();
      if (navigator.onLine) {
        const [snapshot, aeds] = await Promise.all([
          this.#api.getSnapshot(serverView.incidentId),
          this.#api.getAeds(serverView.incidentId),
        ]);
        this.#incident.snapshotRevision = snapshot.snapshotRevision;
        await this.#store.saveIncident(this.#incident);
        this.#emit(
          "online",
          aeds.candidates.length
            ? "本機 API 與 AED 資料已連線"
            : "本機 API 已連線；AED 真實資料尚未載入",
          aeds.candidates.length > 0,
        );
      }
    } catch (error) {
      this.#emit(navigator.onLine ? "degraded" : "offline", userMessageForApiError(error));
    }
  }

  async #saveReport(report: PendingReport): Promise<void> {
    const incident = this.#incident;
    const store = this.#store;
    const identity = this.#identity;
    if (!incident || !store || !identity) return;

    const previousStateRevision = incident.stateRevision ?? 0;
    const nextModeRevision = report.type === "mode.changed" ? incident.modeRevision + 1 : incident.modeRevision;
    const nextIncident: RuntimeIncident = {
      ...incident,
      interactionMode: report.type === "mode.changed" ? report.detail.interactionMode : incident.interactionMode,
      stateRevision: previousStateRevision + 1,
      modeRevision: nextModeRevision,
      guidancePaused: true,
      updatedAt: new Date().toISOString(),
    };
    const event: Omit<EventBatchEvent, "clientSequence"> = {
      eventId: report.type === "action.reported" ? report.eventId ?? crypto.randomUUID() : crypto.randomUUID(),
      type: report.type,
      detail: report.detail,
      clientId: identity.clientId,
      clientInstanceId: identity.clientInstanceId,
      clientTime: new Date().toISOString(),
      authorityEpoch: incident.authorityEpoch ?? 1,
      stateRevision: previousStateRevision,
      modeRevision: nextModeRevision,
      ruleVersion: identity.ruleVersion,
    };
    await store.saveSequencedEvent(nextIncident, event, {
      expiresAt: new Date(Date.now() + INCIDENT_LIFETIME_MS).toISOString(),
    });
    this.#incident = nextIncident;
    this.#applyPausedPolicy();
    await this.#flush();
    if (
      report.type === "mode.changed" &&
      report.detail.interactionMode === "voice_guidance" &&
      this.#resumeRequested &&
      this.#sync?.state === "idle"
    ) {
      this.#live?.sendControl(this.#envelope({ type: "resume.request" }));
    }
  }

  #queueReport(report: PendingReport): Promise<void> {
    const task = this.#reportQueue.then(() => this.#saveReport(report));
    this.#reportQueue = task.catch(() => undefined);
    return task;
  }

  async #flush(): Promise<void> {
    if (!this.#sync || !this.#incident || !navigator.onLine) {
      if (!navigator.onLine) this.#emit("offline", "目前離線，操作已保留在此裝置");
      return;
    }
    try {
      await this.#sync.flush(this.#incident.incidentId);
      const saved = await this.#store?.loadIncident(this.#incident.incidentId);
      if (saved) this.#incident = saved;
      if (this.#sync.state === "idle") this.#emit("online", "救援紀錄已同步");
    } catch {
      // EventBatchSync already exposes the durable error state.
    }
  }

  #createLiveSocket(): void {
    if (!this.#identity || !this.#incident || !this.#session) return;
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    this.#live = new LiveSocket({
      url: `${protocol}//${location.host}/v1/incidents/${this.#identity.incidentId}/live`,
      currentModeRevision: () => this.#incident?.modeRevision ?? 0,
      authenticate: async () => ({
        type: "auth",
        token: this.#session!.sessionToken,
        envelope: this.#envelope({ type: "session.hello", lastAcknowledgedClientSequence: null }),
      }),
    });
    this.#live.subscribeState((state) => {
      if (state !== "online") this.#mediaGate.stopAll();
      if (state === "reconnecting") this.#emit("offline", "Live 連線中斷，正在重新連線");
    });
    this.#live.subscribeMessage((message) => this.#receiveLive(message));
  }

  #receiveLive(message: LiveServerMessage): void {
    if (message.type === "session.ready") {
      this.#mediaGate.stopAll();
      this.#emit("online", "Live 已連線，語音保持暫停");
      return;
    }
    if (message.type === "resume.accepted" && this.#resumeRequested) {
      void this.#startCapture();
      return;
    }
    if (message.type === "error") {
      this.suspend();
      this.#emit("degraded", `Live 暫時不可用：${String(message.code ?? "unknown")}`);
    }
  }

  async #startCapture(): Promise<void> {
    const incident = this.#incident;
    if (!incident || incident.interactionMode !== "voice_guidance") return;
    const accepted = this.#mediaGate.applyPolicy({
      interactionMode: incident.interactionMode,
      guidancePaused: false,
      modeRevision: incident.modeRevision,
    });
    if (!accepted) return;
    try {
      await this.#mediaGate.startCapture(incident.modeRevision, (samples) => {
        const sampleRate = this.#microphone.sampleRate;
        if (!sampleRate || !this.#incident) return;
        this.#encoder ??= new Pcm16Encoder(sampleRate);
        const bytes = this.#encoder.encode(samples);
        if (bytes.length === 0) return;
        this.#live?.sendMedia(this.#envelope({
          type: "media.frame",
          frame: {
            sessionId: this.#session!.actorId,
            sequence: ++this.#mediaSequence,
            modeRevision: this.#incident.modeRevision,
            contentType: "audio/pcm;rate=16000" as const,
            data: bytesToBase64(bytes),
          },
        }));
      });
      this.#emit("online", "Live 語音理解已啟用");
    } catch (error) {
      this.suspend();
      this.#emit("degraded", permissionMessage(error));
    }
  }

  #createLifecycle(): void {
    this.#lifecycle = new RuntimeLifecycle({
      stopMedia: () => this.suspend(),
      pauseTimers: () => undefined,
      onSuspend: () => this.#emit(navigator.onLine ? "online" : "offline", "頁面已暫停；返回後需手動恢復語音"),
      onResumeAvailable: () => this.#emit(navigator.onLine ? "online" : "offline", "頁面已返回；語音仍保持暫停"),
      onOnline: () => this.onOnline(),
      onOffline: () => this.#emit("offline", "目前離線，操作會保留在此裝置"),
      cleanupExpired: async () => {
        await this.#store?.purgeExpired();
      },
      onCleanupError: () => this.#emit("degraded", "過期資料清理失敗"),
    });
    this.#lifecycle.start();
  }

  #applyPausedPolicy(): void {
    if (!this.#incident) return;
    this.#mediaGate.applyPolicy({
      interactionMode: this.#incident.interactionMode,
      guidancePaused: true,
      modeRevision: this.#incident.modeRevision,
    });
  }

  #envelope<T>(payload: T): LiveEnvelope<T> {
    if (!this.#identity || !this.#incident) throw new Error("Incident is not initialized");
    return {
      protocolVersion: 1,
      messageId: crypto.randomUUID(),
      incidentId: this.#incident.incidentId,
      clientId: this.#identity.clientId,
      clientInstanceId: this.#identity.clientInstanceId,
      clientSequence: ++this.#liveSequence,
      clientTime: new Date().toISOString(),
      authorityEpoch: this.#incident.authorityEpoch ?? 1,
      stateRevision: this.#incident.stateRevision ?? 0,
      modeRevision: this.#incident.modeRevision,
      payload,
    };
  }

  #emit(phase: IntegrationPhase, message: string, aedDataAvailable?: boolean): void {
    this.#onStatus({
      phase,
      message,
      incidentId: this.#incident?.incidentId,
      interactionMode: this.#incident?.interactionMode,
      stateRevision: this.#incident?.stateRevision,
      modeRevision: this.#incident?.modeRevision,
      snapshotRevision: this.#incident?.snapshotRevision,
      aedDataAvailable,
    });
  }
}

function reconcileIncident(local: RuntimeIncident | undefined, server: IncidentView): RuntimeIncident {
  const useLocalMode = local && local.modeRevision >= server.modeRevision;
  return {
    incidentId: server.incidentId,
    interactionMode: useLocalMode ? local.interactionMode : server.interactionMode,
    modeRevision: Math.max(local?.modeRevision ?? 0, server.modeRevision),
    stateRevision: Math.max(local?.stateRevision ?? 0, server.stateRevision),
    snapshotRevision: Math.max(local?.snapshotRevision ?? 0, server.snapshotRevision),
    authorityEpoch: server.authorityEpoch,
    ruleVersion: server.ruleVersion,
    guidancePaused: true,
    updatedAt: new Date().toISOString(),
    expiresAt: new Date(Date.now() + INCIDENT_LIFETIME_MS).toISOString(),
    snapshot: local?.snapshot,
    reconciledState: local?.reconciledState,
  };
}

function provisionalIncident(identity: PrimaryIdentity): RuntimeIncident {
  const now = new Date();
  return {
    incidentId: identity.incidentId,
    interactionMode: "call_119",
    modeRevision: 0,
    stateRevision: 0,
    snapshotRevision: 0,
    authorityEpoch: 1,
    ruleVersion: identity.ruleVersion,
    guidancePaused: true,
    updatedAt: now.toISOString(),
    expiresAt: new Date(now.getTime() + INCIDENT_LIFETIME_MS).toISOString(),
  };
}

function permissionMessage(error: unknown): string {
  return error instanceof DOMException && error.name === "NotAllowedError"
    ? "麥克風權限未開啟，仍可使用畫面與按鈕流程"
    : "Live 語音目前無法使用，仍可使用畫面與按鈕流程";
}

export const incidentRuntime = new IncidentRuntime();
