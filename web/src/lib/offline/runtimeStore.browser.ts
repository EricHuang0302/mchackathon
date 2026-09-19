import {
  RuntimeStore,
  type RuntimeIncident,
} from "./runtimeStore";
import type { EventBatchEvent } from "../connection/eventBatchSync";
import { EventBatchSync } from "../connection/eventBatchSync";
import { RestClient } from "../connection/restClient";
import demoFlow from "../../../../rules/flows/demo-v1.flow.yaml?raw";
import demoTemplates from "../../../../rules/templates/demo-v1.zh-TW.templates.yaml?raw";
import { installRuleBundle, loadRuleBundle } from "../rules";

const FIRST_ID = "11111111-1111-4111-8111-111111111111";
const SECOND_ID = "22222222-2222-4222-8222-222222222222";

void run();

async function run(): Promise<void> {
  const databaseName = `runtime-store-test-${crypto.randomUUID()}`;
  let store = new RuntimeStore({ databaseName });
  try {
    const incident: RuntimeIncident = {
      incidentId: "incident",
      interactionMode: "on_call",
      modeRevision: 2,
      guidancePaused: false,
      updatedAt: "2026-09-19T00:00:00Z",
    };
    const event = makeEvent(SECOND_ID, 2);
    await store.saveEvent(incident, event);
    await store.saveEvent(incident, makeEvent(FIRST_ID, 1));

    assertEqual((await store.loadIncident("incident"))?.interactionMode, "on_call");
    assertEqual(
      (await store.listPendingEvents("incident", 50)).map(
        ({ eventId }) => eventId,
      ),
      [FIRST_ID, SECOND_ID],
    );

    await store.close();
    store = new RuntimeStore({ databaseName });
    let uploadCount = 0;
    const sync = new EventBatchSync(
      new RestClient({
        baseUrl: location.origin,
        fetchImpl: async () => {
          uploadCount++;
          return Response.json({
            acknowledgements: [
              { eventId: FIRST_ID, status: "accepted" },
              { eventId: SECOND_ID, status: "accepted" },
            ],
            stateRevision: 4,
            modeRevision: 2,
            snapshotRevision: 1,
            authorityEpoch: 1,
            lastAcknowledgedClientSequence: 2,
          });
        },
      }),
      store,
    );
    await sync.flush("incident");
    assertEqual(uploadCount, 1);
    assertEqual(await store.listPendingEvents("incident", 50), []);

    await store.saveReconciledState(
      "incident",
      { interactionMode: "voice_guidance", stateRevision: 4 },
      { preserveLocalMode: true },
    );
    const restored = await store.loadIncident("incident");
    assertEqual(restored?.interactionMode, "on_call");
    assertEqual(restored?.modeRevision, 2);

    const thirdId = crypto.randomUUID();
    const fourthId = crypto.randomUUID();
    const third = await store.saveSequencedEvent(
      incident,
      withoutSequence(makeEvent(thirdId, 0)),
    );
    const fourth = await store.saveSequencedEvent(
      incident,
      withoutSequence(makeEvent(fourthId, 0)),
    );
    assertEqual([third.clientSequence, fourth.clientSequence], [1, 2]);
    await store.acknowledgeEvents([thirdId, fourthId]);

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

    const installedRule = await installRuleBundle(store, {
      flowText: demoFlow,
      templatesText: demoTemplates,
      flowSource: "demo-v1.flow.yaml",
      templatesSource: "demo-v1.zh-TW.templates.yaml",
    }, { allowUnreviewedDemo: true });
    await store.close();
    store = new RuntimeStore({ databaseName });
    const restoredRule = await loadRuleBundle(store, "demo-v1", {
      allowUnreviewedDemo: true,
    });
    assertEqual(restoredRule?.contentHash, installedRule.contentHash);

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

function withoutSequence(
  event: EventBatchEvent,
): Omit<EventBatchEvent, "clientSequence"> {
  const { clientSequence: _clientSequence, ...draft } = event;
  return draft;
}

function assertEqual(actual: unknown, expected: unknown): void {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(
      `Expected ${JSON.stringify(expected)}, received ${JSON.stringify(actual)}`,
    );
  }
}
