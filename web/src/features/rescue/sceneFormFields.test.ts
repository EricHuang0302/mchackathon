import { assert, test } from "vitest";

import { OBSERVATION_KEYS } from "./snapshotFields";
import {
  DEVICE_ONLY_KEYS,
  parseFieldValue,
  SCENE_FORM_FIELDS,
  SECTION_ORDER,
} from "./sceneFormFields";

test("every snapshot observation key is either typed in or captured by the device", () => {
  const covered = new Set<string>([
    ...DEVICE_ONLY_KEYS,
    ...SCENE_FORM_FIELDS.map((field) => field.key),
  ]);
  const missing = OBSERVATION_KEYS.filter((key) => !covered.has(key));
  assert.deepEqual(missing, [], `no input renders these keys: ${missing.join(", ")}`);
  assert.equal(covered.size, OBSERVATION_KEYS.length);
});

test("every field belongs to a rendered section", () => {
  const rendered = new Set<string>(SECTION_ORDER);
  const orphans = SCENE_FORM_FIELDS.filter((field) => !rendered.has(field.section));
  assert.deepEqual(orphans.map((field) => field.key), []);
});

test("a blank answer stays unobserved while 'unknown' is reported", () => {
  assert.equal(parseFieldValue({ kind: "tristate" }, ""), undefined);
  assert.equal(parseFieldValue({ kind: "tristate" }, "unknown"), "unknown");
  assert.equal(parseFieldValue({ kind: "tristate" }, "true"), true);
  assert.equal(parseFieldValue({ kind: "tristate" }, "false"), false);
  assert.equal(parseFieldValue({ kind: "text" }, "   "), undefined);
  assert.equal(parseFieldValue({ kind: "number", min: 0 }, "3"), 3);
  assert.equal(parseFieldValue({ kind: "number", min: 0 }, "abc"), undefined);
  assert.equal(
    parseFieldValue({ kind: "datetime" }, "2026-09-20T02:43"),
    new Date("2026-09-20T02:43").toISOString(),
  );
});
