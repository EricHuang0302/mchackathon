import { assert, test } from "vitest";

import { RuntimeLifecycle } from "./runtimeLifecycle";

test("suspends once and never resumes media automatically", () => {
  const documentTarget = new FakeDocument();
  const windowTarget = new EventTarget();
  const suspended: string[] = [];
  const resumeAvailable: string[] = [];
  let mediaStops = 0;
  let timerPauses = 0;
  let cleanups = 0;
  const lifecycle = new RuntimeLifecycle({
    stopMedia: () => mediaStops++,
    pauseTimers: () => timerPauses++,
    onSuspend: (reason) => suspended.push(reason),
    onResumeAvailable: (reason) => resumeAvailable.push(reason),
    cleanupExpired: () => {
      cleanups++;
    },
    document: documentTarget,
    window: windowTarget,
  });

  lifecycle.start();
  assert.equal(cleanups, 1);
  documentTarget.visibilityState = "hidden";
  documentTarget.dispatchEvent(new Event("visibilitychange"));
  windowTarget.dispatchEvent(new Event("pagehide"));

  assert.deepEqual(suspended, ["hidden"]);
  assert.equal(mediaStops, 1);
  assert.equal(timerPauses, 1);
  assert.equal(lifecycle.suspended, true);

  documentTarget.visibilityState = "visible";
  windowTarget.dispatchEvent(new Event("pageshow"));
  assert.equal(cleanups, 2);
  assert.deepEqual(resumeAvailable, ["pageshow"]);
  assert.equal(mediaStops, 1);
  assert.equal(timerPauses, 1);
  assert.equal(lifecycle.suspended, true);

  lifecycle.resumeAfterUserAction();
  assert.equal(lifecycle.suspended, false);

  lifecycle.beforeTelephoneHandoff();
  assert.deepEqual(suspended, ["hidden", "telephone"]);
  assert.equal(mediaStops, 2);
  assert.equal(timerPauses, 2);
  assert.equal(lifecycle.suspended, true);
});

class FakeDocument extends EventTarget {
  visibilityState: DocumentVisibilityState = "visible";
}
