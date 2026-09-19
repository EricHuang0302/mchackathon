import { assert, test } from "vitest";

import { MediaGate } from "./mediaGate";

test("call mode synchronously stops outputs and rejects stale work", async () => {
  const played: string[] = [];
  const samples: number[] = [];
  let playbackStops = 0;
  let captureStops = 0;
  let timerStops = 0;

  const gate = new MediaGate<string, number>(
    {
      enqueue: (value) => played.push(value),
      stopAll: () => playbackStops++,
    },
    {
      start: async (onSample) => onSample(1),
      stop: () => captureStops++,
    },
    { stop: () => timerStops++ },
  );

  assert.equal(gate.enqueuePlayback("blocked", 0), false);
  assert.equal(
    gate.applyPolicy({
      interactionMode: "voice_guidance",
      guidancePaused: false,
      modeRevision: 1,
    }),
    true,
  );
  assert.equal(gate.enqueuePlayback("allowed", 1), true);
  assert.equal(await gate.startCapture(1, (sample) => samples.push(sample)), true);

  assert.equal(
    gate.applyPolicy({
      interactionMode: "on_call",
      guidancePaused: false,
      modeRevision: 2,
    }),
    true,
  );

  assert.deepEqual(played, ["allowed"]);
  assert.deepEqual(samples, [1]);
  assert.equal(playbackStops, 1);
  assert.equal(captureStops, 1);
  assert.equal(timerStops, 1);
  assert.equal(gate.status.captureActive, false);
  assert.equal(gate.enqueuePlayback("stale", 1), false);
  assert.equal(
    gate.applyPolicy({
      interactionMode: "voice_guidance",
      guidancePaused: false,
      modeRevision: 1,
    }),
    false,
  );
});
