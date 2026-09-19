import { assert, test } from "vitest";

import { BrowserPcmPlayback } from "./pcmPlayback";

test("queues PCM without overlap and stops every source", async () => {
  const starts: number[] = [];
  let resumes = 0;
  let stops = 0;
  let disconnects = 0;
  const sources: FakeSource[] = [];
  const context = {
    state: "suspended",
    currentTime: 4,
    destination: {},
    resume: async () => {
      resumes++;
      context.state = "running";
    },
    close: async () => {
      context.state = "closed";
    },
    createBuffer: (_channels: number, length: number, sampleRate: number) => ({
      duration: length / sampleRate,
      copyToChannel: () => undefined,
    }),
    createBufferSource: () => {
      const source = new FakeSource(starts, () => stops++, () => disconnects++);
      sources.push(source);
      return source;
    },
  };
  const playback = new BrowserPcmPlayback({
    createContext: () => context as unknown as AudioContext,
  });

  await playback.enable();
  playback.enqueue({ samples: new Float32Array(8_000), sampleRate: 8_000 });
  playback.enqueue({ samples: new Float32Array(4_000), sampleRate: 8_000 });

  assert.equal(resumes, 1);
  assert.deepEqual(starts, [4, 5]);
  assert.equal(playback.enabled, true);

  playback.stopAll();
  assert.equal(stops, 2);
  assert.equal(disconnects, 2);
});

class FakeSource {
  buffer: AudioBuffer | null = null;
  onended: (() => void) | null = null;
  readonly #starts: number[];
  readonly #onStop: () => void;
  readonly #onDisconnect: () => void;

  constructor(
    starts: number[],
    onStop: () => void,
    onDisconnect: () => void,
  ) {
    this.#starts = starts;
    this.#onStop = onStop;
    this.#onDisconnect = onDisconnect;
  }

  connect(): void {}

  disconnect(): void {
    this.#onDisconnect();
  }

  start(at: number): void {
    this.#starts.push(at);
  }

  stop(): void {
    this.#onStop();
  }
}
