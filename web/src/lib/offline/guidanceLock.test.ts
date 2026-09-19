import { assert, test } from "vitest";

import { acquireGuidanceLock } from "./guidanceLock";

test("holds one guidance lock until the lease is released", async () => {
  let requestedName = "";
  let callbackFinished = false;
  const lockManager = {
    request: async (
      name: string,
      _options: LockOptions,
      callback: (lock: Lock | null) => Promise<void>,
    ) => {
      requestedName = name;
      await callback({ name, mode: "exclusive" } as Lock);
      callbackFinished = true;
    },
  } as unknown as LockManager;

  const lease = await acquireGuidanceLock("incident", lockManager);

  assert.equal(lease.supported, true);
  assert.equal(lease.acquired, true);
  assert.equal(callbackFinished, false);
  assert.equal(
    requestedName,
    "first-aid-copilot:incident:incident:guidance",
  );

  lease.release();
  await lease.done;
  assert.equal(callbackFinished, true);
});
