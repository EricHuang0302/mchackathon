import type {
  AedAssignmentReadResponse,
  AedAssignmentResponse,
  CameraObservationProposal,
  IncidentView,
  LiveObservationProposal,
  ObservationInput,
  RuleEvaluationResponse,
  SceneSnapshotResponse,
  SceneImageAnalysisResponse,
  SessionResponse,
  ShareScope,
} from "../../types/api";
import type { RescueMode } from "../../types/rescue";
import { BrowserMicrophone } from "../media/microphone";
import { MediaGate } from "../media/mediaGate";
import { bytesToBase64, Pcm16Encoder } from "../media/pcm16";
import type { CameraFrame } from "../media/camera";
import { buildCameraConfirmationObservations } from "../media/cameraObservations";
import { BrowserPcmPlayback } from "../media/pcmPlayback";
import { BrowserTemplateSpeech, GuidanceOutput } from "../media/templateSpeech";
import { RuntimeLifecycle } from "../offline/runtimeLifecycle";
import { RuntimeStore, type RuntimeIncident } from "../offline/runtimeStore";
import { ruleObservationsFromSnapshot, snapshotObservationFor } from "../rules/observationMapping";
import { installBundledRule, RuleError } from "../rules";
import { ApiClient, ApiClientError, userMessageForApiError } from "./apiClient";
import { EventBatchSync, type EventBatchEvent } from "./eventBatchSync";
import { LiveSocket, type LiveEnvelope, type LiveServerMessage } from "./liveSocket";
import { RestClient } from "./restClient";
import {
  clearIncidentSession,
  getAedRunnerHelper,
  saveAedRunnerHelper,
  getOrCreateSession,
  getPrimaryIdentity,
  refreshSession,
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
  | { type: "action.reported"; detail: { action: string }; eventId?: string }
  | { type: "call.reported"; detail: { source: "user"; reportedState: CallReportedState }; eventId?: string };

type CallReportedState = "attempted" | "active" | "ended" | "failed" | "uncertain";

const INCIDENT_LIFETIME_MS = 72 * 60 * 60 * 1_000;

export class IncidentRuntime {
  readonly #pcm = new BrowserPcmPlayback();
  readonly #speech = new BrowserTemplateSpeech();
  readonly #playback = new GuidanceOutput(this.#pcm, this.#speech);
  readonly #microphone = new BrowserMicrophone();
  readonly #mediaGate = new MediaGate(this.#playback, this.#microphone, {
    stop: () => undefined,
  });
  readonly #pendingReports: PendingReport[] = [];
  #reportQueue: Promise<void> = Promise.resolve();
  #observationQueue: Promise<SceneSnapshotResponse | null> = Promise.resolve(null);
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
  #latestSnapshot: SceneSnapshotResponse | null = null;
  #latestAedRunnerHelperId: string | null = null;
  #demoMode = false;
  #resumeRequested = false;
  #onStatus: (status: IntegrationStatus) => void = () => undefined;
  #onObservationProposal: (proposal: LiveObservationProposal) => void = () => undefined;

  configure(
    onStatus: (status: IntegrationStatus) => void,
    options: { demoMode?: boolean; onObservationProposal?: (proposal: LiveObservationProposal) => void } = {},
  ): void {
    this.#onStatus = onStatus;
    this.#demoMode = options.demoMode ?? false;
    this.#onObservationProposal = options.onObservationProposal ?? (() => undefined);
  }

  initialize(): Promise<void> {
    if (this.#sync) return Promise.resolve();
    this.#starting ??= this.#initialize().finally(() => {
      this.#starting = null;
    });
    return this.#starting;
  }

  start(): Promise<void> {
    return this.initialize();
  }

  reportModeChange(targetMode: RescueMode, reason: ModeReason): void {
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

  reportCallState(reportedState: CallReportedState): void {
    const report: PendingReport = {
      type: "call.reported",
      detail: { source: "user", reportedState },
      eventId: crypto.randomUUID(),
    };
    if (!this.#incident) {
      this.#pendingReports.push(report);
      void this.initialize();
      return;
    }
    void this.#queueReport(report);
  }

  resumeGuidance(): void {
    this.#resumeRequested = true;
    this.#applyGuidancePolicy();
    void this.#pcm.enable().catch((error) => {
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
    await this.initialize();
    if (!this.#api || !this.#incident) throw new Error("Incident is not connected");
    const helperId = scope === "ems_viewer" ? undefined : crypto.randomUUID();
    const body = {
      scope,
      helperId,
      expiresInSeconds: 300,
      idempotencyKey: crypto.randomUUID(),
    };
    try {
      const share = await this.#api.createShare(this.#incident.incidentId, body);
      if (scope === "aed_runner" && helperId) this.#rememberAedRunner(helperId);
      return share;
    } catch (error) {
      if (!(error instanceof ApiClientError) || error.status !== 401) throw error;
      this.#session = await refreshSession("primary");
      this.#api = new ApiClient(this.#session.sessionToken);
      const share = await this.#api.createShare(this.#incident.incidentId, body);
      if (scope === "aed_runner" && helperId) this.#rememberAedRunner(helperId);
      return share;
    }
  }

  // The runner's helperId is minted here and never echoed back by the runner,
  // so a primary that reloads would otherwise lose it and never be able to
  // dispatch. Keep it beside the incident session it belongs to.
  #rememberAedRunner(helperId: string): void {
    this.#latestAedRunnerHelperId = helperId;
    if (this.#incident) saveAedRunnerHelper({ incidentId: this.#incident.incidentId, helperId });
  }

  #aedRunnerHelperId(): string | null {
    if (this.#latestAedRunnerHelperId) return this.#latestAedRunnerHelperId;
    const stored = getAedRunnerHelper();
    if (stored && this.#incident && stored.incidentId === this.#incident.incidentId) {
      this.#latestAedRunnerHelperId = stored.helperId;
    }
    return this.#latestAedRunnerHelperId;
  }

  async dispatchAed(): Promise<AedAssignmentResponse> {
    await this.initialize();
    if (!this.#api || !this.#incident) throw new Error("Incident is not connected");
    const helperId = this.#aedRunnerHelperId();
    if (!helperId) {
      throw new Error("請先建立 AED 取件者邀請，並請協助者掃描接受後再指派。");
    }
    return this.#api.dispatchAed(this.#incident.incidentId, {
      helperId,
      expectedStateRevision: this.#incident.stateRevision ?? 0,
    });
  }

  async getAedAssignment(): Promise<AedAssignmentReadResponse | null> {
    await this.initialize();
    const helperId = this.#aedRunnerHelperId();
    if (!this.#api || !this.#incident || !helperId) return null;
    return this.#api.getAedAssignment(this.#incident.incidentId, helperId);
  }

  async addObservation(key: string, value: string): Promise<void> {
    await this.addObservations([{
      observationId: crypto.randomUUID(), key, value, source: "button",
      observedAt: new Date().toISOString(), confirmation: "uncertain", evidenceEventIds: [],
    }]);
  }

  getSnapshot(): Promise<SceneSnapshotResponse> {
    return this.#refreshSnapshot();
  }

  addObservations(observations: ObservationInput[]): Promise<SceneSnapshotResponse> {
    const task = this.#observationQueue.then(() => this.#writeObservations(observations));
    this.#observationQueue = task.catch(() => null);
    return task;
  }

  async analyzeSceneImage(frame: CameraFrame): Promise<SceneImageAnalysisResponse> {
    await this.initialize();
    if (!this.#api || !this.#incident) throw new Error("Incident is not connected");
    if (frame.modeRevision !== this.#incident.modeRevision) {
      throw new DOMException("Camera frame revision is stale", "AbortError");
    }
    if (frame.blob.size > 700_000) throw new Error("相片檔案過大，請重新拍攝。")
    const mimeType = frame.blob.type;
    if (mimeType !== "image/jpeg" && mimeType !== "image/webp") {
      throw new Error("不支援的相片格式。")
    }
    const imageBase64 = bytesToBase64(new Uint8Array(await frame.blob.arrayBuffer()));
    const analysis = await this.#api.analyzeSceneImage(this.#incident.incidentId, {
      imageBase64,
      mimeType,
      capturedAt: frame.capturedAt,
      expectedModeRevision: frame.modeRevision,
    });
    if (frame.modeRevision !== this.#incident.modeRevision) {
      throw new DOMException("Camera analysis revision is stale", "AbortError");
    }
    return analysis;
  }

  async confirmCameraProposals(
    proposals: CameraObservationProposal[],
    values: Record<CameraObservationProposal["key"], CameraObservationProposal["value"]>,
  ): Promise<SceneSnapshotResponse> {
    return this.addObservations(buildCameraConfirmationObservations(proposals, values));
  }

  async confirmObservation(
    proposal: LiveObservationProposal,
    value: boolean | "unknown",
  ): Promise<{ snapshot: SceneSnapshotResponse; evaluation: RuleEvaluationResponse }> {
    const observedAt = new Date().toISOString();
    const observationId = crypto.randomUUID();
    // A proposal names its fact in the rule namespace, which the snapshot
    // projection silently discards. Restate it first, and leave the snapshot
    // untouched when the fact cannot be restated without inventing something.
    const projected = snapshotObservationFor(proposal.key, value);
    const snapshot = projected
      ? await this.addObservations([{
        observationId,
        key: projected.key,
        value: projected.value,
        source: "manual_report",
        observedAt,
        confirmation: "user_confirmed",
        evidenceEventIds: [],
      }])
      : await this.#refreshSnapshot();
    const evaluation = await this.evaluateRules([{
      observationId,
      key: proposal.key,
      value,
      source: "button",
      observedAt,
      confirmation: "confirmed",
      evidenceEventIds: [],
    }]);
    return { snapshot, evaluation };
  }

  async evaluateRules(
    observations: Array<Record<string, unknown>> = [],
    trigger: Record<string, unknown> = { type: "observation" },
  ): Promise<RuleEvaluationResponse> {
    await this.initialize();
    await this.#reportQueue;
    await this.#flush();
    if (!this.#api || !this.#incident) throw new Error("Incident is not connected");
    // The rules use their own key namespace, so the confirmed snapshot has to
    // be translated before it can reach them. An explicitly supplied
    // observation wins over the projected one for the same key.
    const merged = new Map<string, Record<string, unknown>>();
    for (const derived of ruleObservationsFromSnapshot(this.#latestSnapshot)) {
      merged.set(derived.key, derived as unknown as Record<string, unknown>);
    }
    for (const supplied of observations) {
      const key = supplied.key;
      merged.set(typeof key === "string" ? key : crypto.randomUUID(), supplied);
    }
    return this.#api.evaluateRules(this.#incident.incidentId, {
      expectedStateRevision: this.#incident.stateRevision ?? 0,
      expectedModeRevision: this.#incident.modeRevision,
      trigger,
      observations: [...merged.values()],
      timers: [],
    });
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
    this.#observationQueue = Promise.resolve(null);
    this.#latestSnapshot = null;
    this.#latestAedRunnerHelperId = null;
  }

  async #initialize(): Promise<void> {
    this.#emit("initializing", "正在建立本機救援連線…");
    try {
      this.#store ??= new RuntimeStore();
      await this.#store.purgeExpired();
      this.#identity ??= getPrimaryIdentity();
      try {
        await installBundledRule(this.#store, this.#identity.ruleVersion, {
          allowUnreviewedDemo: this.#demoMode,
        });
      } catch (error) {
        if (!(error instanceof RuleError && error.detail === "review_not_approved")) {
          this.#emit("degraded", "離線規則包無法使用；線上與按鈕流程不受影響");
        }
      }
      const restored = await this.#store.loadIncident(this.#identity.incidentId);
      this.#incident ??= restored ?? provisionalIncident(this.#identity);
      this.#incident = { ...this.#incident, guidancePaused: true };
      await this.#store.saveIncident(this.#incident);
      this.#applyGuidancePolicy();
      this.#store.subscribeStatus((status) => {
        if (status === "degraded") this.#emit("degraded", "裝置儲存空間目前不可用");
      });
      if (!this.#lifecycle) this.#createLifecycle();

      while (this.#pendingReports.length > 0) {
        await this.#queueReport(this.#pendingReports.shift()!);
      }

      this.#session = await getOrCreateSession("primary");
      this.#api = new ApiClient(this.#session.sessionToken);
      let serverView: IncidentView;
      try {
        serverView = await this.#api.createIncident({
          incidentId: this.#identity.incidentId,
          primaryClientId: this.#identity.clientId,
          ruleVersion: this.#identity.ruleVersion,
        });
      } catch (error) {
        if (!(error instanceof ApiClientError) || error.status !== 401) throw error;
        this.#session = await refreshSession("primary");
        this.#api = new ApiClient(this.#session.sessionToken);
        serverView = await this.#api.createIncident({
          incidentId: this.#identity.incidentId,
          primaryClientId: this.#identity.clientId,
          ruleVersion: this.#identity.ruleVersion,
        });
      }
      this.#incident = reconcileIncident(this.#incident, serverView);
      await this.#store.saveIncident(this.#incident);
      this.#applyGuidancePolicy();

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
        try {
          let [snapshot, aeds] = await Promise.all([
            this.#api.getSnapshot(serverView.incidentId),
            this.#api.getAeds(serverView.incidentId),
          ]);
          if (this.#demoMode && snapshot.snapshotRevision === 0) {
            await this.#api.addObservations(serverView.incidentId, {
              expectedSnapshotRevision: 0,
              idempotencyKey: crypto.randomUUID(),
              observations: demoObservations(),
            });
            snapshot = await this.#api.getSnapshot(serverView.incidentId);
          }
          this.#latestSnapshot = snapshot;
          this.#incident.snapshotRevision = snapshot.snapshotRevision;
          await this.#store.saveIncident(this.#incident);
          this.#emit(
            "online",
            aeds.candidates.length
              ? "本機 API 與 AED 資料已連線"
              : "本機 API 已連線；取得位置後會搜尋附近 AED",
            aeds.candidates.length > 0,
          );
        } catch (error) {
          console.warn("optional incident data refresh failed", error);
          this.#emit("online", "本機 API 已連線；現場資料將於操作時重試", false);
        }
      }
    } catch (error) {
      console.error("incident runtime initialization failed", error);
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
      // Only mode.changed, incident_state.updated and decision.committed advance
      // the authoritative state revision, and the backend owns all three. A plain
      // report must not inflate it here: reconcileIncident keeps the larger of the
      // local and server values, so an optimistic bump sticks and every later
      // expectedStateRevision check fails with a stale revision.
      stateRevision: previousStateRevision,
      modeRevision: nextModeRevision,
      guidancePaused: true,
      updatedAt: new Date().toISOString(),
    };
    const event: Omit<EventBatchEvent, "clientSequence"> = {
      eventId: "eventId" in report ? report.eventId ?? crypto.randomUUID() : crypto.randomUUID(),
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
    this.#applyGuidancePolicy();
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

  async #refreshSnapshot(): Promise<SceneSnapshotResponse> {
    await this.initialize();
    if (!this.#api || !this.#incident) throw new Error("Incident is not connected");
    const snapshot = await this.#api.getSnapshot(this.#incident.incidentId);
    this.#latestSnapshot = snapshot;
    this.#incident.snapshotRevision = snapshot.snapshotRevision;
    await this.#store?.saveIncident(this.#incident);
    this.#emit("online", "現場快照已同步");
    return snapshot;
  }

  async #writeObservations(observations: ObservationInput[]): Promise<SceneSnapshotResponse> {
    await this.initialize();
    if (!this.#api || !this.#incident) throw new Error("Incident is not connected");
    let expected = this.#latestSnapshot?.snapshotRevision ?? this.#incident.snapshotRevision ?? 0;
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        const result = await this.#api.addObservations(this.#incident.incidentId, {
          expectedSnapshotRevision: expected,
          idempotencyKey: crypto.randomUUID(),
          observations,
        });
        this.#incident.snapshotRevision = result.snapshotRevision;
        await this.#store?.saveIncident(this.#incident);
        return await this.#refreshSnapshot();
      } catch (error) {
        if (!(error instanceof ApiClientError) || error.code !== "stale_revision" || attempt > 0) {
          this.#emit(navigator.onLine ? "degraded" : "offline", userMessageForApiError(error));
          throw error;
        }
        const current = await this.#refreshSnapshot();
        const accepted = new Set(current.observations.map((item) => item.observationId));
        if (observations.every((item) => accepted.has(item.observationId))) return current;
        expected = current.snapshotRevision;
      }
    }
    throw new Error("Observation update failed");
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
    if (message.type === "observation.proposed") {
      const proposal = observationProposalFromLive(message);
      if (proposal) this.#onObservationProposal(proposal);
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
        stopPlaybackOnSpeech(samples, () => this.#playback.stopAll());
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

  #applyGuidancePolicy(): void {
    if (!this.#incident) return;
    this.#mediaGate.applyPolicy({
      interactionMode: this.#incident.interactionMode,
      // Paused unless the user explicitly resumed guidance and the incident is
      // actually in voice_guidance. suspend() clears #resumeRequested, so a
      // reconnect, a page resume or a call interrupt can never unpause here.
      guidancePaused: !(this.#resumeRequested && this.#incident.interactionMode === "voice_guidance"),
      modeRevision: this.#incident.modeRevision,
    });
  }

  /**
   * Reads one approved template line. The gate rejects it outright unless audio
   * is currently allowed for this mode revision, so call-mode silence and stale
   * instructions are enforced in one place.
   */
  speakTemplate(text: string): boolean {
    if (!this.#incident || !text) return false;
    return this.#mediaGate.enqueuePlayback({ text }, this.#incident.modeRevision);
  }

  stopSpeech(): void {
    this.#speech.stopAll();
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

export function hasSpeechActivity(samples: Float32Array, threshold = 0.02): boolean {
  if (samples.length === 0) return false;
  let energy = 0;
  for (const sample of samples) energy += sample * sample;
  return Math.sqrt(energy / samples.length) >= threshold;
}

export function stopPlaybackOnSpeech(
  samples: Float32Array,
  stopAll: () => void,
): boolean {
  if (!hasSpeechActivity(samples)) return false;
  stopAll();
  return true;
}

export function observationProposalFromLive(message: LiveServerMessage): LiveObservationProposal | null {
  if (message.type !== "observation.proposed") return null;
  const proposal = message.observation;
  if (!proposal || typeof proposal !== "object") return null;
  const value = (proposal as { value?: unknown }).value;
  const key = (proposal as { key?: unknown }).key;
  if ((key !== "responsive" && key !== "breathing_normal") || (typeof value !== "boolean" && value !== "unknown")) return null;
  const candidate = proposal as Partial<LiveObservationProposal>;
  if (
    typeof candidate.observationId !== "string" ||
    message.messageId !== candidate.observationId ||
    candidate.source !== "model_proposal" ||
    candidate.confirmation !== "proposed" ||
    typeof candidate.observedAt !== "string" ||
    !Array.isArray(candidate.evidenceEventIds) ||
    !candidate.evidenceEventIds.every((item) => typeof item === "string")
  ) return null;
  return candidate as LiveObservationProposal;
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

function demoObservations(): ObservationInput[] {
  const observedAt = new Date().toISOString();
  const values: Array<[string, ObservationInput["value"]]> = [
    ["location.coordinates", { latitude: 25.033, longitude: 121.565 }],
    ["location.address", "台北市信義區市府路 1 號"],
    ["location.landmark", "一樓大廳"],
    ["circumstances.whatHappened", "一名成人突然倒地"],
    ["patient.responsive", false],
    ["patient.breathing", false],
    ["hazards.present", false],
  ];
  return values.map(([key, value]) => ({
    observationId: crypto.randomUUID(),
    key,
    value,
    source: "manual_report",
    observedAt,
    confirmation: "user_confirmed",
    evidenceEventIds: [],
  }));
}

export const incidentRuntime = new IncidentRuntime();
