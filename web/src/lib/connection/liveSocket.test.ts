import { assert, test } from "vitest";

import {
  LiveSocket,
  type LiveAuthMessage,
  type LiveEnvelope,
  type LiveServerMessage,
  type SocketClose,
  type WebSocketLike,
} from "./liveSocket";

test("authenticates before becoming online and filters stale duplicates", async () => {
  const sockets: FakeSocket[] = [];
  const received: string[] = [];
  let modeRevision = 2;
  const live = new LiveSocket({
    url: "wss://example.test/v1/incidents/demo/live",
    authenticate: async () => auth(),
    currentModeRevision: () => modeRevision,
    createSocket: () => {
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    },
  });
  live.subscribeMessage((message) => received.push(message.type));

  live.connect();
  sockets[0]!.open();
  await Promise.resolve();
  assert.equal(live.state, "connecting");
  assert.deepEqual(JSON.parse(String(sockets[0]!.sent[0])), auth());

  sockets[0]!.message({ type: "session.ready", modeRevision: 1 });
  assert.equal(live.state, "connecting");
  sockets[0]!.message({ type: "session.ready", modeRevision: 2 });
  assert.equal(live.state, "online");
  sockets[0]!.message({ type: "media.ack", messageId: "same", modeRevision: 2 });
  sockets[0]!.message({ type: "media.ack", messageId: "same", modeRevision: 2 });
  sockets[0]!.message({ type: "observation.proposed", modeRevision: 1 });
  sockets[0]!.message({ type: "audio.output", modeRevision: 1 });
  assert.deepEqual(received, ["session.ready", "media.ack"]);

  assert.equal(live.sendControl(envelope("outbound", 2)), true);
  sockets[0]!.bufferedAmount = 65_537;
  assert.equal(
    live.sendMedia({
      ...envelope("media", 2),
      payload: {
        type: "media.frame",
        frame: {
          sessionId: "session",
          sequence: 1,
          modeRevision: 2,
          contentType: "audio/pcm;rate=16000",
          data: "AA==",
        },
      },
    }),
    false,
  );
  sockets[0]!.bufferedAmount = 0;
  assert.equal(
    live.sendMedia({
      ...envelope("stale-media", 2),
      payload: {
        type: "media.frame",
        frame: {
          sessionId: "session",
          sequence: 2,
          modeRevision: 1,
          contentType: "audio/pcm;rate=16000",
          data: "AA==",
        },
      },
    }),
    false,
  );
  modeRevision = 3;
  assert.equal(live.sendControl(envelope("old-outbound", 2)), false);
});

test("reconnects with backoff but stops after an access error", async () => {
  const sockets: FakeSocket[] = [];
  const delays: number[] = [];
  const retries: Array<() => void> = [];
  const live = new LiveSocket({
    url: "wss://example.test/live",
    authenticate: async () => auth(),
    currentModeRevision: () => 2,
    createSocket: () => {
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    },
    schedule: (callback, delay) => {
      retries.push(callback);
      delays.push(delay);
      return callback;
    },
    cancelSchedule: () => undefined,
    random: () => 0.5,
  });

  live.connect();
  sockets[0]!.open();
  await Promise.resolve();
  sockets[0]!.message({ type: "session.ready", modeRevision: 2 });
  sockets[0]!.finish({ code: 1006, reason: "network", wasClean: false });
  assert.equal(live.state, "reconnecting");
  assert.deepEqual(delays, [500]);

  retries[0]!();
  sockets[1]!.open();
  await Promise.resolve();
  sockets[1]!.message({ type: "error", code: "unauthorized" });
  assert.equal(live.state, "offline");
  assert.equal(sockets[1]!.closedReason, "Live access denied");
});

test("waits for the browser online event", () => {
  const target = new EventTarget();
  let online = false;
  let sockets = 0;
  const live = new LiveSocket({
    url: "wss://example.test/live",
    authenticate: async () => auth(),
    currentModeRevision: () => 2,
    isOnline: () => online,
    onlineTarget: target,
    createSocket: () => {
      sockets++;
      return new FakeSocket();
    },
  });

  live.connect();
  assert.equal(live.state, "offline");
  assert.equal(sockets, 0);
  online = true;
  target.dispatchEvent(new Event("online"));
  assert.equal(sockets, 1);
  assert.equal(live.state, "connecting");
});

class FakeSocket implements WebSocketLike {
  readyState = 0;
  bufferedAmount = 0;
  binaryType: BinaryType = "blob";
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: SocketClose) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  readonly sent: Array<string | ArrayBuffer | ArrayBufferView | Blob> = [];
  closedReason?: string;

  send(data: string | ArrayBuffer | ArrayBufferView | Blob): void {
    this.sent.push(data);
  }

  close(_code?: number, reason?: string): void {
    this.readyState = 3;
    this.closedReason = reason;
  }

  open(): void {
    this.readyState = 1;
    this.onopen?.(new Event("open"));
  }

  message(value: LiveServerMessage): void {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(value) }));
  }

  finish(event: SocketClose): void {
    this.readyState = 3;
    this.onclose?.(event);
  }
}

function auth(): LiveAuthMessage {
  return {
    type: "auth",
    token: "synthetic-token",
    envelope: {
      ...envelope("hello", 2),
      payload: {
        type: "session.hello",
        lastAcknowledgedClientSequence: 7,
      },
    },
  };
}

function envelope(messageId: string, modeRevision: number): LiveEnvelope {
  return {
    protocolVersion: 1,
    messageId,
    incidentId: "incident",
    clientId: "client",
    clientInstanceId: "tab",
    clientSequence: 8,
    clientTime: "2026-09-19T00:00:00Z",
    authorityEpoch: 1,
    stateRevision: 1,
    modeRevision,
    payload: { type: "mode.silence" },
  };
}
