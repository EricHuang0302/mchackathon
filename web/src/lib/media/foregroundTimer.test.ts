import { assert, test } from "vitest";

import {
  ForegroundTimer,
  type TimerClock,
  type TimerTick,
} from "./foregroundTimer";

test("reschedules from the observed time instead of replaying missed ticks", () => {
  let now = 0;
  let scheduled: (() => void) | undefined;
  let scheduledDelay = 0;
  let cancellations = 0;
  const ticks: TimerTick[] = [];
  const clock: TimerClock = {
    now: () => now,
    schedule: (callback, delayMs) => {
      scheduled = callback;
      scheduledDelay = delayMs;
      return callback;
    },
    cancel: () => cancellations++,
  };
  const timer = new ForegroundTimer(1_000, (tick) => ticks.push(tick), clock);

  timer.start();
  assert.equal(scheduledDelay, 1_000);

  now = 2_500;
  scheduled?.();

  assert.deepEqual(ticks, [{ scheduledAt: 1_000, observedAt: 2_500 }]);
  assert.equal(scheduledDelay, 1_000);

  timer.pause();
  assert.equal(timer.running, false);
  assert.equal(cancellations, 1);

  now = 10_000;
  timer.resume();
  assert.equal(scheduledDelay, 1_000);
});
