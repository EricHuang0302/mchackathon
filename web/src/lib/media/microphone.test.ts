import { assert, expect, test } from "vitest";

import { BrowserMicrophone } from "./microphone";

test("captures mono samples and releases the audio graph", async () => {
  let stopped = 0;
  let disconnected = 0;
  let resumed = 0;
  let closed = 0;
  let loadedUrl = "";
  const samples: Float32Array[] = [];
  const track = { readyState: "live", stop: () => stopped++ };
  const stream = {
    getTracks: () => [track],
    getAudioTracks: () => [track],
  } as unknown as MediaStream;
  const node = () => ({
    connect: () => undefined,
    disconnect: () => disconnected++,
  });
  const source = node();
  const mute = { ...node(), gain: { value: 1 } };
  const worklet = {
    ...node(),
    port: { onmessage: null as ((event: MessageEvent) => void) | null },
  };
  const context = {
    state: "suspended",
    sampleRate: 48_000,
    destination: {},
    resume: async () => resumed++,
    close: async () => closed++,
    audioWorklet: {
      addModule: async (url: string) => {
        loadedUrl = url;
      },
    },
    createMediaStreamSource: () => source,
    createGain: () => mute,
  } as unknown as AudioContext;
  const microphone = new BrowserMicrophone({
    mediaDevices: {
      getUserMedia: async () => stream,
    } as Pick<MediaDevices, "getUserMedia">,
    createContext: () => context,
    createWorkletNode: () => worklet as unknown as AudioWorkletNode,
    workletUrl: "pcm-worklet.js",
  });

  await microphone.start((sample) => samples.push(sample));
  const sample = new Float32Array([0.25]);
  worklet.port.onmessage?.(new MessageEvent("message", { data: sample }));

  assert.equal(resumed, 1);
  assert.equal(loadedUrl, "pcm-worklet.js");
  assert.deepEqual(samples, [sample]);
  assert.equal(mute.gain.value, 0);
  assert.equal(microphone.active, true);
  assert.equal(microphone.sampleRate, 48_000);

  microphone.stop();
  await Promise.resolve();
  assert.equal(stopped, 1);
  assert.equal(disconnected, 3);
  assert.equal(closed, 1);
  assert.equal(microphone.sampleRate, undefined);
});

test("a denied microphone permission closes the audio context", async () => {
  let closed = 0;
  const denied = new DOMException("denied", "NotAllowedError");
  const context = {
    state: "suspended",
    sampleRate: 48_000,
    resume: async () => undefined,
    close: async () => {
      closed++;
    },
  } as unknown as AudioContext;
  const microphone = new BrowserMicrophone({
    createContext: () => context,
    mediaDevices: {
      getUserMedia: async () => {
        throw denied;
      },
    } as Pick<MediaDevices, "getUserMedia">,
  });

  await expect(microphone.start(() => undefined)).rejects.toBe(denied);
  assert.equal(microphone.active, false);
  assert.equal(closed, 1);
});
