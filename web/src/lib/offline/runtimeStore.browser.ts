import {
  RuntimeStore,
  type RuntimeIncident,
} from "./runtimeStore";
import type { EventBatchEvent } from "../connection/eventBatchSync";

void run();

async function run(): Promise<void> {
  const databaseName = `runtime-store-test-${crypto.randomUUID()}`;
  const store = new RuntimeStore({ databaseName });
  try {
    const incident: RuntimeIncident = {
      incidentId: "incident",
      interactionMode: "on_call",
      modeRevision: 2,
      guidancePaused: false,
      updatedAt: "2026-09-19T00:00:00Z",
    };
    const event = makeEvent("second", 2);
    await store.saveEvent(incident, event);
    await store.saveEvent(incident, makeEvent("first", 1));

    assertEqual((await store.loadIncident("incident"))?.interactionMode, "on_call");
    assertEqual(
      (await store.listPendingEvents("incident", 50)).map(
        ({ eventId }) => eventId,
      ),
      ["first", "second"],
    );

    await store.acknowledgeEvents(["first"]);
    await store.markConflicts([
      { eventId: "second", code: "stale_revision" },
    ]);
    assertEqual(await store.listPendingEvents("incident", 50), []);

    await store.saveReconciledState(
      "incident",
      { interactionMode: "voice_guidance", stateRevision: 4 },
      { preserveLocalMode: true },
    );
    const restored = await store.loadIncident("incident");
    assertEqual(restored?.interactionMode, "on_call");
    assertEqual(restored?.modeRevision, 2);

    await store.saveCommand({
      commandId: "command",
      incidentId: "incident",
      status: "completed",
      modeRevision: 2,
      authorityEpoch: 1,
      updatedAt: "2026-09-19T00:00:00Z",
    });
    assertEqual((await store.loadCommand("command"))?.status, "completed");

    await store.saveRuleBundle({
      ruleVersion: "expired-rule",
      bundle: { synthetic: true },
      savedAt: "2026-09-19T00:00:00Z",
      expiresAt: "2026-09-19T00:00:01Z",
    });
    assertEqual(await store.purgeExpired(Date.parse("2026-09-19T00:00:02Z")), 1);
    assertEqual(await store.loadRuleBundle("expired-rule"), undefined);

    document.body.dataset.result = "pass";
    document.body.textContent = "PASS";
  } catch (error) {
    document.body.dataset.result = "fail";
    document.body.textContent = `FAIL: ${String(error)}`;
  } finally {
    await store.close();
    indexedDB.deleteDatabase(databaseName);
  }
}

function makeEvent(eventId: string, clientSequence: number): EventBatchEvent {
  return {
    eventId,
    type: "action.reported",
    detail: { action: "synthetic" },
    clientId: "client",
    clientInstanceId: "tab",
    clientSequence,
    clientTime: "2026-09-19T00:00:00Z",
    authorityEpoch: 1,
    stateRevision: 3,
    modeRevision: 2,
    ruleVersion: "demo-v1",
  };
}

function assertEqual(actual: unknown, expected: unknown): void {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(
      `Expected ${JSON.stringify(expected)}, received ${JSON.stringify(actual)}`,
    );
  }
}
