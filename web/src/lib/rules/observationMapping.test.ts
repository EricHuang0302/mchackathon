import { assert, test } from "vitest";

import { ruleObservationsFromSnapshot } from "./observationMapping";
import type { SceneSnapshotResponse, SnapshotField } from "../../types/api";

let counter = 0;
const nextId = () => `id-${++counter}`;

const field = (
  key: string,
  value: SnapshotField["value"],
  confirmation: SnapshotField["provenance"]["confirmation"] = "confirmed",
): SnapshotField => ({
  key,
  section: "patientCondition",
  value,
  provenance: {
    source: "user_report",
    confirmation,
    observedAt: "2026-09-20T02:43:00.000Z",
    receivedAt: "2026-09-20T02:43:00.100Z",
    evidenceEventIds: ["evidence-1"],
    correctedFromEventIds: [],
    observedTimeUncertain: false,
  },
  freshness: "fresh",
  ageSeconds: 1,
  pendingProposals: [],
});

const snapshotOf = (fields: SnapshotField[]) =>
  ({ sections: { patientCondition: fields } } as unknown as SceneSnapshotResponse);

test("translates confirmed snapshot facts into the rule namespace", () => {
  counter = 0;
  const result = ruleObservationsFromSnapshot(
    snapshotOf([
      field("patient.responsive", false),
      field("hazards.present", true),
      field("patient.bleeding", "severe"),
    ]),
    nextId,
  );

  assert.deepEqual(
    result.map(({ key, value }) => ({ key, value })),
    [
      { key: "responsive", value: false },
      { key: "scene_safe", value: false },
      { key: "bleeding_severity", value: "severe" },
    ],
  );
  const [first] = result;
  assert.isDefined(first);
  assert.equal(first.observedAt, "2026-09-20T02:43:00.000Z");
  assert.deepEqual(first.evidenceEventIds, ["evidence-1"]);
});

test("never turns an unobserved or unknown answer into a value", () => {
  const result = ruleObservationsFromSnapshot(
    snapshotOf([
      field("patient.responsive", null),
      field("hazards.present", "unknown"),
      field("patient.bleeding", "unknown"),
    ]),
    nextId,
  );
  assert.deepEqual(result, []);
  assert.deepEqual(ruleObservationsFromSnapshot(null), []);
});

test("refuses a bare proposal, which is below the declared minimum confirmation", () => {
  const proposed = ruleObservationsFromSnapshot(
    snapshotOf([field("patient.responsive", true, "proposed")]),
    nextId,
  );
  assert.deepEqual(proposed, []);

  const reported = ruleObservationsFromSnapshot(
    snapshotOf([field("patient.responsive", true, "reported")]),
    nextId,
  );
  const [only] = reported;
  assert.isDefined(only);
  assert.equal(reported.length, 1);
  assert.equal(only.confirmation, "reported");
});

test("only carries breathing across in the direction that is sound", () => {
  const absent = ruleObservationsFromSnapshot(
    snapshotOf([field("patient.breathing", false)]),
    nextId,
  );
  assert.deepEqual(absent.map(({ key, value }) => ({ key, value })), [
    { key: "breathing_normal", value: false },
  ]);

  // "Breathing" does not establish normal breathing, so it stays unmapped.
  const present = ruleObservationsFromSnapshot(
    snapshotOf([field("patient.breathing", true)]),
    nextId,
  );
  assert.deepEqual(present, []);
});

test("ignores snapshot keys the rule package does not declare", () => {
  const result = ruleObservationsFromSnapshot(
    snapshotOf([field("patient.skinColor", "pale"), field("people.patientCount", 2)]),
    nextId,
  );
  assert.deepEqual(result, []);
});
