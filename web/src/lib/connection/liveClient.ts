import { audioGate } from "../media/audioGate";
import type { IncidentView, SessionResponse } from "../../types/api";
import type { PrimaryIdentity } from "./session";

type LiveState = Pick<IncidentView, "stateRevision" | "modeRevision" | "authorityEpoch" | "interactionMode">;

export class LiveClient {
  private socket: WebSocket | null = null;
  private stopped = false;
  private reconnectTimer: number | null = null;
  private sequence = 0;
  private current: LiveState;
  constructor(private readonly session: SessionResponse, private readonly identity: PrimaryIdentity, view: IncidentView, private readonly onStatus: (status: string) => void) {
    this.current = view;
  }
  update(view: LiveState) { this.current = view; }
  connect() {
    this.stopped = false;
    audioGate.silence();
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    this.socket = new WebSocket(`${protocol}//${location.host}/v1/incidents/${this.identity.incidentId}/live`);
    this.socket.addEventListener("open", () => {
      this.onStatus("live_connected_muted");
      this.socket?.send(JSON.stringify({ type: "auth", token: this.session.sessionToken, envelope: this.envelope({ type: "session.hello" }) }));
    });
    this.socket.addEventListener("message", (event) => this.receive(JSON.parse(String(event.data)) as Record<string, unknown>));
    this.socket.addEventListener("close", () => { audioGate.silence(); this.onStatus("live_disconnected"); if (!this.stopped) this.reconnectTimer = window.setTimeout(() => this.connect(), 1000); });
  }
  private envelope(payload: Record<string, unknown>) { return { protocolVersion: 1, messageId: crypto.randomUUID(), incidentId: this.identity.incidentId, clientId: this.identity.clientId, clientInstanceId: this.identity.clientInstanceId, clientSequence: ++this.sequence, clientTime: new Date().toISOString(), authorityEpoch: this.current.authorityEpoch, stateRevision: this.current.stateRevision, modeRevision: this.current.modeRevision, payload }; }
  private receive(message: Record<string, unknown>) {
    if (message.type === "session.ready") {
      audioGate.silence();
      this.current = { interactionMode: message.interactionMode as LiveState["interactionMode"], stateRevision: Number(message.stateRevision), modeRevision: Number(message.modeRevision), authorityEpoch: Number(message.authorityEpoch) };
      this.onStatus("live_ready_muted");
      return;
    }
    if (Number(message.modeRevision) !== this.current.modeRevision) return;
    if (message.type === "resume.accepted") { audioGate.acceptResume(this.current.modeRevision); this.onStatus("voice_ready"); }
    if (message.type === "error") { audioGate.silence(); this.onStatus(`live_error:${String(message.code)}`); }
  }
  silence() { audioGate.silence(); if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify(this.envelope({ type: "mode.silence" }))); }
  requestResume() { audioGate.requestResume(); if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify(this.envelope({ type: "resume.request" }))); }
  close() { this.stopped = true; if (this.reconnectTimer !== null) window.clearTimeout(this.reconnectTimer); this.socket?.close(); this.socket = null; audioGate.silence(); }
}
