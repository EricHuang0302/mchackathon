import { assert, expect, test } from "vitest";

import {
  EventBatchSync,
  type EventBatchEvent,
  type EventBatchStore,
  type EventConflict,
} from "./eventBatchSync";
import { RestClient } from "./restClient";

const FIRST_ID = "11111111-1111-4111-8111-111111111111";
const SECOND_ID = "22222222-2222-4222-8222-222222222222";

test("acknowledges only confirmed events and stops on conflict", async () => {
  const events = [event(FIRST_ID, 1), event(SECOND_ID, 2)];
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
          { eventId: FIRST_ID, status: "accepted" },
          { eventId: SECOND_ID, status: "conflict", code: "stale_revision" },
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

  assert.deepEqual(acknowledged, [FIRST_ID]);
  assert.deepEqual(conflicts, [
    { eventId: SECOND_ID, code: "stale_revision" },
  ]);
  assert.deepEqual(reconciled, [
    {
      acknowledgements: [
        { eventId: FIRST_ID, status: "accepted" },
        { eventId: SECOND_ID, status: "conflict", code: "stale_revision" },
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

  await sync.flush("incident/unsafe");
  assert.equal(requestedUrls.length, 1);
});

test("rejects malformed acknowledgements without marking events", async () => {
  const acknowledged: string[] = [];
  const sync = new EventBatchSync(
    new RestClient({
      baseUrl: "https://example.test",
      fetchImpl: async () => Response.json({ acknowledgements: [] }),
    }),
    {
      listPendingEvents: async () => [event(FIRST_ID, 1)],
      acknowledgeEvents: async (eventIds) => {
        acknowledged.push(...eventIds);
      },
      markConflicts: async () => undefined,
      saveReconciledState: async () => undefined,
    },
  );

  await expect(sync.flush("incident")).rejects.toThrow(
    "Invalid event batch response",
  );
  assert.deepEqual(acknowledged, []);
  assert.equal(sync.state, "error");
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
