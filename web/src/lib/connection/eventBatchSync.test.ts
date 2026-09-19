import { assert, test } from "vitest";

import {
  EventBatchSync,
  type EventBatchEvent,
  type EventBatchStore,
  type EventConflict,
} from "./eventBatchSync";
import { RestClient } from "./restClient";

test("acknowledges only confirmed events and stops on conflict", async () => {
  const events = [event("first", 1), event("second", 2)];
  const acknowledged: string[] = [];
  const conflicts: EventConflict[] = [];
  const reconciled: unknown[] = [];
  const store: EventBatchStore = {
    listPendingEvents: async () => events,
    acknowledgeEvents: async (eventIds) => {
      acknowledged.push(...eventIds);
    },
    markConflicts: async (values) => {
      conflicts.push(...values);
    },
    saveReconciledState: async (_incidentId, state, options) => {
      assert.deepEqual(options, { preserveLocalMode: true });
      reconciled.push(state);
    },
  };
  const requestedUrls: string[] = [];
  const client = new RestClient({
    baseUrl: "https://example.test",
    fetchImpl: async (input) => {
      requestedUrls.push(String(input));
      return Response.json({
        acknowledgements: [
          { eventId: "first", status: "accepted" },
          { eventId: "second", status: "conflict", code: "stale_revision" },
        ],
        stateRevision: 4,
        modeRevision: 2,
        snapshotRevision: 1,
        authorityEpoch: 1,
        lastAcknowledgedClientSequence: 1,
      });
    },
  });
  const sync = new EventBatchSync(client, store);

  await sync.flush("incident/unsafe");

  assert.deepEqual(acknowledged, ["first"]);
  assert.deepEqual(conflicts, [
    { eventId: "second", code: "stale_revision" },
  ]);
  assert.deepEqual(reconciled, [
    {
      acknowledgements: [
        { eventId: "first", status: "accepted" },
        { eventId: "second", status: "conflict", code: "stale_revision" },
      ],
      stateRevision: 4,
      modeRevision: 2,
      snapshotRevision: 1,
      authorityEpoch: 1,
      lastAcknowledgedClientSequence: 1,
    },
  ]);
  assert.equal(sync.state, "resyncing");
  assert.deepEqual(requestedUrls, [
    "https://example.test/v1/incidents/incident%2Funsafe/event-batches",
  ]);
});

function event(eventId: string, clientSequence: number): EventBatchEvent {
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
