import { assert, test } from "vitest";

import { MediaGate } from "./mediaGate";
import { BrowserTemplateSpeech, GuidanceOutput } from "./templateSpeech";
import type { PcmPlaybackChunk } from "./pcmPlayback";
import type { SpeechRequest } from "./templateSpeech";

interface FakeUtterance {
  text: string;
  lang: string;
}

const fakeSynthesis = () => {
  const spoken: FakeUtterance[] = [];
  const calls: string[] = [];
  const synthesis = {
    cancel: () => calls.push("cancel"),
    speak: (utterance: FakeUtterance) => {
      calls.push("speak");
      spoken.push(utterance);
    },
  } as unknown as SpeechSynthesis;
  return { synthesis, spoken, calls };
};

const speechFor = (fake: ReturnType<typeof fakeSynthesis>) =>
  new BrowserTemplateSpeech({
    synthesis: fake.synthesis,
    createUtterance: (text) => ({ text, lang: "" }) as unknown as SpeechSynthesisUtterance,
  });

test("cancels the previous line before speaking a newer one", () => {
  const fake = fakeSynthesis();
  const speech = speechFor(fake);

  speech.enqueue({ text: "持續胸外按壓" });
  speech.enqueue({ text: "改為回復姿勢" });

  assert.deepEqual(fake.calls, ["cancel", "speak", "cancel", "speak"]);
  assert.deepEqual(fake.spoken.map((u) => u.text), ["持續胸外按壓", "改為回復姿勢"]);
  assert.deepEqual(fake.spoken.map((u) => u.lang), ["zh-TW", "zh-TW"]);
});

test("ignores empty text and reports unavailable synthesis instead of throwing", () => {
  const fake = fakeSynthesis();
  speechFor(fake).enqueue({ text: "" });
  assert.deepEqual(fake.calls, []);

  const missing = new BrowserTemplateSpeech({ synthesis: undefined });
  assert.equal(missing.available, false);
  missing.enqueue({ text: "持續胸外按壓" });
  missing.stopAll();
});

test("the media gate refuses speech outside voice guidance and silences it on call mode", () => {
  const fake = fakeSynthesis();
  const speech = speechFor(fake);
  const pcmStops: string[] = [];
  const pcm = { enqueue: () => undefined, stopAll: () => pcmStops.push("stop") };
  const output = new GuidanceOutput(pcm, speech);
  const capture = { start: async () => undefined, stop: () => undefined };
  const gate = new MediaGate<SpeechRequest | PcmPlaybackChunk>(output, capture, {
    stop: () => undefined,
  });

  // Default policy is call_119 with guidance paused: nothing may be read out.
  assert.equal(gate.enqueuePlayback({ text: "持續胸外按壓" }, 0), false);
  assert.deepEqual(fake.spoken, []);

  assert.equal(
    gate.applyPolicy({ interactionMode: "voice_guidance", guidancePaused: false, modeRevision: 1 }),
    true,
  );
  assert.equal(gate.enqueuePlayback({ text: "持續胸外按壓" }, 1), true);
  assert.equal(fake.spoken.length, 1);

  // A stale mode revision must never reach the speaker.
  assert.equal(gate.enqueuePlayback({ text: "過期指令" }, 0), false);
  assert.equal(fake.spoken.length, 1);

  // Entering call mode cancels spoken output alongside the PCM sink.
  gate.applyPolicy({ interactionMode: "on_call", guidancePaused: true, modeRevision: 2 });
  assert.equal(fake.calls.at(-1), "cancel");
  assert.deepEqual(pcmStops, ["stop"]);
  assert.equal(gate.enqueuePlayback({ text: "通話中不可出聲" }, 2), false);
  assert.equal(fake.spoken.length, 1);
});
