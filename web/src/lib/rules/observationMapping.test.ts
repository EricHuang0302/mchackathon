import { assert, test } from "vitest";

import { ruleObservationsFromSnapshot, snapshotObservationFor } from "./observationMapping";
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

test("only infers from patient.breathing in the direction that is sound", () => {
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

  // The explicit answer is carried in both directions.
  const explicit = ruleObservationsFromSnapshot(
    snapshotOf([field("patient.breathingNormal", true)]),
    nextId,
  );
  assert.deepEqual(explicit.map(({ key, value }) => ({ key, value })), [
    { key: "breathing_normal", value: true },
  ]);
});

test("ignores snapshot keys the rule package does not declare", () => {
  const result = ruleObservationsFromSnapshot(
    snapshotOf([field("patient.skinColor", "pale"), field("people.patientCount", 2)]),
    nextId,
  );
  assert.deepEqual(result, []);
});

test("restates a confirmed proposal in the snapshot namespace", () => {
  assert.deepEqual(snapshotObservationFor("responsive", false), {
    key: "patient.responsive",
    value: false,
  });
  assert.deepEqual(snapshotObservationFor("scene_safe", true), {
    key: "hazards.present",
    value: false,
  });
  assert.deepEqual(snapshotObservationFor("bleeding_severity", "minor"), {
    key: "patient.bleeding",
    value: "minor",
  });
});

test("restates breathing in the key that asks the same question", () => {
  assert.deepEqual(snapshotObservationFor("breathing_normal", true), {
    key: "patient.breathingNormal",
    value: true,
  });
  assert.deepEqual(snapshotObservationFor("breathing_normal", false), {
    key: "patient.breathingNormal",
    value: false,
  });
});

test("refuses to restate what cannot be restated", () => {
  assert.equal(snapshotObservationFor("responsive", "unknown"), null);
  assert.equal(snapshotObservationFor("scene_safe", "unknown"), null);
  assert.equal(snapshotObservationFor("bleeding_severity", "nope"), null);
  assert.equal(snapshotObservationFor("patient_age_years", 40 as unknown as string), null);
});
