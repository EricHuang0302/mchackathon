import { assert, test } from "vitest";

import {
  LiveSocket,
  type LiveEnvelope,
  type SocketClose,
  type WebSocketLike,
} from "./liveSocket";

test("drops duplicate and stale messages and reconnects with backoff", () => {
  const sockets: FakeSocket[] = [];
  const delays: number[] = [];
  const retries: Array<() => void> = [];
  const received: string[] = [];
  let modeRevision = 2;
  const live = new LiveSocket({
    url: "wss://example.test/v1/incidents/demo/live",
    currentModeRevision: () => modeRevision,
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
  live.subscribeMessage((message) => received.push(message.messageId));

  live.connect();
  assert.equal(live.state, "connecting");
  sockets[0]!.open();
  assert.equal(live.state, "online");

  sockets[0]!.message(envelope("accepted", 2));
  sockets[0]!.message(envelope("accepted", 2));
  sockets[0]!.message(envelope("stale", 1));
  assert.deepEqual(received, ["accepted"]);

  assert.equal(live.sendControl(envelope("outbound", 2)), true);
  modeRevision = 3;
  assert.equal(live.sendControl(envelope("old-outbound", 2)), false);

  sockets[0]!.finish({ code: 1006, reason: "network", wasClean: false });
  assert.equal(live.state, "reconnecting");
  assert.deepEqual(delays, [500]);

  retries[0]!();
  assert.equal(sockets.length, 2);
  assert.equal(live.state, "reconnecting");
});

class FakeSocket implements WebSocketLike {
  readyState = 0;
  binaryType: BinaryType = "blob";
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: SocketClose) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  readonly sent: Array<string | ArrayBuffer | ArrayBufferView | Blob> = [];

  send(data: string | ArrayBuffer | ArrayBufferView | Blob): void {
    this.sent.push(data);
  }

  close(): void {
    this.readyState = 3;
  }

  open(): void {
    this.readyState = 1;
    this.onopen?.(new Event("open"));
  }

  message(value: LiveEnvelope): void {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(value) }));
  }

  finish(event: SocketClose): void {
    this.readyState = 3;
    this.onclose?.(event);
  }
}

function envelope(messageId: string, modeRevision: number): LiveEnvelope {
  return {
    protocolVersion: 1,
    messageId,
    incidentId: "incident",
    clientId: "client",
    clientInstanceId: "tab",
    clientSequence: 1,
    clientTime: "2026-09-19T00:00:00Z",
    authorityEpoch: 1,
    stateRevision: 1,
    modeRevision,
    payload: { synthetic: true },
  };
}
