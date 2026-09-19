import { assert, test } from "vitest";

import { registerOfflineWorker } from "./serviceWorkerRegistration";

test("caches approved assets but keeps updates waiting during an incident", async () => {
  const active = new FakeWorker();
  const waiting = new FakeWorker();
  const registration = {
    active,
    waiting,
    installing: null,
    addEventListener: () => undefined,
  } as unknown as ServiceWorkerRegistration;
  let incidentActive = true;
  const handle = await registerOfflineWorker({
    scriptUrl: "/runtime-service-worker.js",
    approvedAssets: ["/", "/assets/app.js"],
    incidentActive: () => incidentActive,
    container: {
      register: async () => registration,
    } as unknown as ServiceWorkerContainer,
  });

  assert.ok(handle);
  assert.deepEqual(active.messages, [
    { type: "cache.approved", assets: ["/", "/assets/app.js"] },
  ]);
  assert.equal(handle.activateUpdate(), false);
  assert.deepEqual(waiting.messages, [
    { type: "cache.approved", assets: ["/", "/assets/app.js"] },
  ]);

  assert.equal(handle.activateUpdate(true), true);
  assert.deepEqual(waiting.messages.at(-1), { type: "activate.update" });

  incidentActive = false;
  assert.equal(handle.activateUpdate(), true);
  assert.deepEqual(waiting.messages.at(-1), { type: "activate.update" });
});

class FakeWorker {
  readonly messages: unknown[] = [];

  postMessage(message: unknown): void {
    this.messages.push(message);
  }
}
