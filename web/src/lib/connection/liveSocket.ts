export type LiveConnectionState =
  | "offline"
  | "connecting"
  | "online"
  | "reconnecting";

export interface LiveEnvelope<T = unknown> {
  protocolVersion: 1;
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

export interface LiveAuthMessage {
  type: "auth";
  token: string;
  envelope: LiveEnvelope<{
    type: "session.hello";
    lastAcknowledgedClientSequence: number | null;
  }>;
}

export type LiveServerMessage = {
  type: string;
  messageId?: string;
  modeRevision?: number;
  code?: string;
  [key: string]: unknown;
};

export interface MediaFrame {
  sessionId: string;
  sequence: number;
  modeRevision: number;
  contentType: "audio/pcm;rate=16000" | "image/jpeg";
  data: string;
}

export type MediaEnvelope = LiveEnvelope<{
  type: "media.frame";
  frame: MediaFrame;
}>;

export interface SocketClose {
  code: number;
  reason: string;
  wasClean: boolean;
}

export interface WebSocketLike {
  readyState: number;
  bufferedAmount: number;
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
  authenticate: () => Promise<LiveAuthMessage>;
  currentModeRevision: () => number;
  createSocket?: (url: string) => WebSocketLike;
  shouldReconnect?: (event: SocketClose) => boolean;
  schedule?: (callback: () => void, delayMs: number) => unknown;
  cancelSchedule?: (handle: unknown) => void;
  random?: () => number;
  isOnline?: () => boolean;
  onlineTarget?: Pick<EventTarget, "addEventListener" | "removeEventListener">;
  maxSeenMessages?: number;
  maxBufferedMediaBytes?: number;
}

type StateListener = (state: LiveConnectionState) => void;
type MessageListener = (message: LiveServerMessage) => void;

const OPEN = 1;
const FATAL_CODES = new Set(["unauthorized", "expired"]);

export class LiveSocket {
  readonly #options: Required<
    Pick<
      LiveSocketOptions,
      | "createSocket"
      | "shouldReconnect"
      | "schedule"
      | "cancelSchedule"
      | "random"
      | "isOnline"
      | "maxSeenMessages"
      | "maxBufferedMediaBytes"
    >
  > &
    Pick<
      LiveSocketOptions,
      "url" | "authenticate" | "currentModeRevision" | "onlineTarget"
    >;
  readonly #stateListeners = new Set<StateListener>();
  readonly #messageListeners = new Set<MessageListener>();
  readonly #seen = new Set<string>();
  readonly #seenOrder: string[] = [];
  #socket?: WebSocketLike;
  #retryHandle?: unknown;
  #attempt = 0;
  #manualClose = false;
  #waitingOnline = false;
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
      isOnline:
        options.isOnline ??
        (() => typeof navigator === "undefined" || navigator.onLine !== false),
      onlineTarget:
        options.onlineTarget ??
        (typeof window === "undefined" ? undefined : window),
      maxSeenMessages: options.maxSeenMessages ?? 1_000,
      maxBufferedMediaBytes: options.maxBufferedMediaBytes ?? 65_536,
    };
  }

  connect(): void {
    this.#manualClose = false;
    this.#clearRetry();
    if (!this.#options.isOnline()) {
      this.#waitForOnline();
      return;
    }
    this.#open();
  }

  disconnect(code = 1000, reason = "client disconnect"): void {
    this.#manualClose = true;
    this.#clearRetry();
    this.#stopWaitingOnline();
    const socket = this.#socket;
    this.#socket = undefined;
    socket?.close(code, reason);
    this.#setState("offline");
  }

  sendControl(envelope: LiveEnvelope): boolean {
    return this.#sendEnvelope(envelope);
  }

  sendMedia(envelope: MediaEnvelope): boolean {
    if (
      envelope.payload.frame.modeRevision !== envelope.modeRevision ||
      (this.#socket?.bufferedAmount ?? 0) >
        this.#options.maxBufferedMediaBytes
    ) {
      return false;
    }
    return this.#sendEnvelope(envelope);
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

    this.#stopWaitingOnline();
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
      void this.#options.authenticate().then(
        (message) => {
          if (this.#socket === socket && socket.readyState === OPEN) {
            socket.send(JSON.stringify(message));
          }
        },
        () => {
          if (this.#socket === socket) {
            this.#manualClose = true;
            socket.close(1000, "Authentication failed");
          }
        },
      );
    };
    socket.onmessage = (event) => {
      if (this.#socket !== socket || typeof event.data !== "string") return;
      this.#receive(event.data, socket);
    };
    socket.onclose = (event) => {
      if (this.#socket !== socket) return;
      this.#socket = undefined;
      if (this.#manualClose || !this.#options.shouldReconnect(event)) {
        this.#setState("offline");
        return;
      }
      if (!this.#options.isOnline()) this.#waitForOnline();
      else this.#scheduleReconnect();
    };
    socket.onerror = () => {
      // The close event owns retry so browsers cannot schedule it twice.
    };
  }

  #receive(raw: string, socket: WebSocketLike): void {
    let message: LiveServerMessage;
    try {
      message = JSON.parse(raw) as LiveServerMessage;
    } catch {
      return;
    }
    if (!isServerMessage(message)) return;

    if (
      typeof message.modeRevision === "number" &&
      message.modeRevision !== this.#options.currentModeRevision()
    ) {
      return;
    }

    if (
      message.type === "error" &&
      (this.#state !== "online" || FATAL_CODES.has(message.code ?? ""))
    ) {
      this.#manualClose = true;
      socket.close(1000, "Live access denied");
      this.#setState("offline");
      return;
    }
    if (message.type === "session.ready") {
      this.#attempt = 0;
      this.#setState("online");
    }
    if (message.messageId && this.#seen.has(message.messageId)) return;
    if (message.messageId) this.#remember(message.messageId);
    for (const listener of this.#messageListeners) listener(message);
  }

  #sendEnvelope(envelope: LiveEnvelope): boolean {
    if (
      this.#state !== "online" ||
      this.#socket?.readyState !== OPEN ||
      envelope.modeRevision !== this.#options.currentModeRevision()
    ) {
      return false;
    }
    this.#socket.send(JSON.stringify(envelope));
    return true;
  }

  #remember(messageId: string): void {
    this.#seen.add(messageId);
    this.#seenOrder.push(messageId);
    if (this.#seenOrder.length <= this.#options.maxSeenMessages) return;
    const oldest = this.#seenOrder.shift();
    if (oldest) this.#seen.delete(oldest);
  }

  #scheduleReconnect(): void {
    this.#setState("reconnecting");
    const base = Math.min(500 * 2 ** this.#attempt, 5_000);
    const delay = base * (0.8 + this.#options.random() * 0.4);
    this.#attempt++;
    this.#retryHandle = this.#options.schedule(() => {
      this.#retryHandle = undefined;
      if (!this.#options.isOnline()) this.#waitForOnline();
      else this.#open();
    }, delay);
  }

  #waitForOnline(): void {
    this.#setState("offline");
    if (this.#waitingOnline || !this.#options.onlineTarget) return;
    this.#waitingOnline = true;
    this.#options.onlineTarget.addEventListener("online", this.#handleOnline);
  }

  readonly #handleOnline = (): void => {
    this.#stopWaitingOnline();
    if (!this.#manualClose) this.#open();
  };

  #stopWaitingOnline(): void {
    if (!this.#waitingOnline) return;
    this.#options.onlineTarget?.removeEventListener("online", this.#handleOnline);
    this.#waitingOnline = false;
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

function isServerMessage(value: unknown): value is LiveServerMessage {
  return (
    value !== null &&
    typeof value === "object" &&
    typeof (value as { type?: unknown }).type === "string"
  );
}
