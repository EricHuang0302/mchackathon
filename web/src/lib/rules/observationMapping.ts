import type { ObservationRecord, SceneSnapshotResponse, SnapshotField } from "../../types/api";

/**
 * The canonical snapshot and the rule package use different key namespaces:
 * the projection stores `patient.responsive` while demo-v1 declares
 * `responsive`. Nothing bridged them, so rule evaluation only ever saw the
 * observations passed in by hand and never the confirmed scene snapshot.
 *
 * This translates the snapshot into the rule namespace. It only carries facts
 * across; it never derives a clinical judgement the user did not report.
 */
export type RuleObservationKey =
  | "scene_safe"
  | "responsive"
  | "breathing_normal"
  | "bleeding_severity";

export interface RuleObservation {
  observationId: string;
  key: RuleObservationKey;
  value: boolean | string;
  source: "button";
  observedAt: string;
  confirmation: "reported" | "confirmed";
  evidenceEventIds: string[];
}

// demo-v1 sets minimumConfirmation "reported" on every key mapped here, so a
// bare proposal must not be promoted into a rule input.
const ACCEPTED_CONFIRMATIONS: ReadonlySet<ObservationRecord["confirmation"]> = new Set([
  "reported",
  "confirmed",
]);

const BLEEDING_SEVERITY: ReadonlySet<string> = new Set([
  "none",
  "minor",
  "severe",
  "life_threatening",
]);

type SnapshotValue = NonNullable<SnapshotField["value"]>;
type Translate = (value: SnapshotValue) => boolean | string | undefined;

const TRANSLATORS: Readonly<Record<string, { key: RuleObservationKey; translate: Translate }>> = {
  // A reported hazard makes the scene unsafe, and no hazard makes it safe.
  "hazards.present": {
    key: "scene_safe",
    translate: (value) => (typeof value === "boolean" ? !value : undefined),
  },
  // The same question under a different name.
  "patient.responsive": {
    key: "responsive",
    translate: (value) => (typeof value === "boolean" ? value : undefined),
  },
  // Only the negative direction is sound. No breathing is certainly not normal
  // breathing, but "breathing" does not rule out agonal gasps, so a positive
  // answer is left unmapped instead of being upgraded into a clinical judgement.
  "patient.breathing": {
    key: "breathing_normal",
    translate: (value) => (value === false ? false : undefined),
  },
  // The scene form already records the enum demo-v1 declares.
  "patient.bleeding": {
    key: "bleeding_severity",
    translate: (value) =>
      typeof value === "string" && BLEEDING_SEVERITY.has(value) ? value : undefined,
  },
};

export function ruleObservationsFromSnapshot(
  snapshot: SceneSnapshotResponse | null | undefined,
  newId: () => string = () => crypto.randomUUID(),
): RuleObservation[] {
  if (!snapshot) return [];
  const observations: RuleObservation[] = [];
  for (const fields of Object.values(snapshot.sections)) {
    for (const field of fields) {
      const mapping = TRANSLATORS[field.key];
      // A null value was never observed, and 'unknown' fails every translator
      // below, so neither can turn into a false.
      if (!mapping || field.value === null) continue;
      if (!ACCEPTED_CONFIRMATIONS.has(field.provenance.confirmation)) continue;
      const value = mapping.translate(field.value);
      if (value === undefined) continue;
      observations.push({
        observationId: newId(),
        key: mapping.key,
        value,
        source: "button",
        observedAt: field.provenance.observedAt ?? new Date().toISOString(),
        confirmation: field.provenance.confirmation as "reported" | "confirmed",
        evidenceEventIds: field.provenance.evidenceEventIds,
      });
    }
  }
  return observations;
}
