export type LiveConnectionState =
  | "offline"
  | "connecting"
  | "online"
  | "reconnecting";

export interface LiveEnvelope<T = unknown> {
  protocolVersion: string | number;
  messageId: string;
  incidentId: string;
  clientId: string;
  clientInstanceId: string;
  clientSequence: number;
  clientTime: string;
  authorityEpoch: number;
  stateRevision: number;
  modeRevision: number;
  payload: T;
}

export interface SocketClose {
  code: number;
  reason: string;
  wasClean: boolean;
}

export interface WebSocketLike {
  readyState: number;
  binaryType: BinaryType;
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onclose: ((event: SocketClose) => void) | null;
  onerror: ((event: Event) => void) | null;
  send(data: string | ArrayBuffer | ArrayBufferView | Blob): void;
  close(code?: number, reason?: string): void;
}

export interface LiveSocketOptions {
  url: string | (() => string);
  currentModeRevision: () => number;
  createSocket?: (url: string) => WebSocketLike;
  shouldReconnect?: (event: SocketClose) => boolean;
  schedule?: (callback: () => void, delayMs: number) => unknown;
  cancelSchedule?: (handle: unknown) => void;
  random?: () => number;
  maxSeenMessages?: number;
}

type StateListener = (state: LiveConnectionState) => void;
type MessageListener = (envelope: LiveEnvelope) => void;

const OPEN = 1;

export class LiveSocket {
  readonly #options: Required<
    Pick<
      LiveSocketOptions,
      | "createSocket"
      | "shouldReconnect"
      | "schedule"
      | "cancelSchedule"
      | "random"
      | "maxSeenMessages"
    >
  > &
    Pick<LiveSocketOptions, "url" | "currentModeRevision">;
  readonly #stateListeners = new Set<StateListener>();
  readonly #messageListeners = new Set<MessageListener>();
  readonly #seen = new Set<string>();
  readonly #seenOrder: string[] = [];
  #socket?: WebSocketLike;
  #retryHandle?: unknown;
  #attempt = 0;
  #manualClose = false;
  #state: LiveConnectionState = "offline";

  constructor(options: LiveSocketOptions) {
    this.#options = {
      ...options,
      createSocket:
        options.createSocket ?? ((url) => new WebSocket(url) as WebSocketLike),
      shouldReconnect: options.shouldReconnect ?? (() => true),
      schedule:
        options.schedule ??
        ((callback, delayMs) => setTimeout(callback, delayMs)),
      cancelSchedule:
        options.cancelSchedule ??
        ((handle) => clearTimeout(handle as ReturnType<typeof setTimeout>)),
      random: options.random ?? Math.random,
      maxSeenMessages: options.maxSeenMessages ?? 1_000,
    };
  }

  connect(): void {
    this.#manualClose = false;
    this.#clearRetry();
    this.#open();
  }

  disconnect(code = 1000, reason = "client disconnect"): void {
    this.#manualClose = true;
    this.#clearRetry();
    const socket = this.#socket;
    this.#socket = undefined;
    socket?.close(code, reason);
    this.#setState("offline");
  }

  sendControl(envelope: LiveEnvelope): boolean {
    if (!this.#canSend(envelope.modeRevision)) return false;
    this.#socket?.send(JSON.stringify(envelope));
    return true;
  }

  sendMedia(
    data: ArrayBuffer | ArrayBufferView | Blob,
    modeRevision: number,
  ): boolean {
    if (!this.#canSend(modeRevision)) return false;
    this.#socket?.send(data);
    return true;
  }

  subscribeState(listener: StateListener): () => void {
    this.#stateListeners.add(listener);
    listener(this.#state);
    return () => this.#stateListeners.delete(listener);
  }

  subscribeMessage(listener: MessageListener): () => void {
    this.#messageListeners.add(listener);
    return () => this.#messageListeners.delete(listener);
  }

  get state(): LiveConnectionState {
    return this.#state;
  }

  #open(): void {
    if (
      this.#socket &&
      (this.#socket.readyState === 0 || this.#socket.readyState === OPEN)
    ) {
      return;
    }

    this.#setState(this.#attempt === 0 ? "connecting" : "reconnecting");
    const url =
      typeof this.#options.url === "function"
        ? this.#options.url()
        : this.#options.url;
    const socket = this.#options.createSocket(url);
    socket.binaryType = "arraybuffer";
    this.#socket = socket;

    socket.onopen = () => {
      if (this.#socket !== socket) return;
      this.#attempt = 0;
      this.#setState("online");
    };
    socket.onmessage = (event) => {
      if (this.#socket !== socket || typeof event.data !== "string") return;
      this.#receive(event.data);
    };
    socket.onclose = (event) => {
      if (this.#socket !== socket) return;
      this.#socket = undefined;
      if (this.#manualClose || !this.#options.shouldReconnect(event)) {
        this.#setState("offline");
        return;
      }
      this.#scheduleReconnect();
    };
    socket.onerror = () => {
      // The close event owns retry so browsers cannot schedule it twice.
    };
  }

  #receive(raw: string): void {
    let envelope: LiveEnvelope;
    try {
      envelope = JSON.parse(raw) as LiveEnvelope;
    } catch {
      return;
    }

    if (
      !isEnvelope(envelope) ||
      envelope.modeRevision !== this.#options.currentModeRevision() ||
      this.#seen.has(envelope.messageId)
    ) {
      return;
    }

    this.#remember(envelope.messageId);
    for (const listener of this.#messageListeners) listener(envelope);
  }

  #remember(messageId: string): void {
    this.#seen.add(messageId);
    this.#seenOrder.push(messageId);
    if (this.#seenOrder.length <= this.#options.maxSeenMessages) return;
    const oldest = this.#seenOrder.shift();
    if (oldest) this.#seen.delete(oldest);
  }

  #canSend(modeRevision: number): boolean {
    return (
      this.#socket?.readyState === OPEN &&
      modeRevision === this.#options.currentModeRevision()
    );
  }

  #scheduleReconnect(): void {
    this.#setState("reconnecting");
    const base = Math.min(500 * 2 ** this.#attempt, 5_000);
    const delay = base * (0.8 + this.#options.random() * 0.4);
    this.#attempt++;
    this.#retryHandle = this.#options.schedule(() => {
      this.#retryHandle = undefined;
      this.#open();
    }, delay);
  }

  #clearRetry(): void {
    if (this.#retryHandle === undefined) return;
    this.#options.cancelSchedule(this.#retryHandle);
    this.#retryHandle = undefined;
  }

  #setState(state: LiveConnectionState): void {
    this.#state = state;
    for (const listener of this.#stateListeners) listener(state);
  }
}

function isEnvelope(value: unknown): value is LiveEnvelope {
  if (value === null || typeof value !== "object") return false;
  const envelope = value as Partial<LiveEnvelope>;
  return (
    (typeof envelope.protocolVersion === "string" ||
      typeof envelope.protocolVersion === "number") &&
    typeof envelope.messageId === "string" &&
    typeof envelope.incidentId === "string" &&
    typeof envelope.clientId === "string" &&
    typeof envelope.clientInstanceId === "string" &&
    typeof envelope.clientSequence === "number" &&
    typeof envelope.clientTime === "string" &&
    typeof envelope.authorityEpoch === "number" &&
    typeof envelope.stateRevision === "number" &&
    typeof envelope.modeRevision === "number" &&
    "payload" in envelope
  );
}
