import { assert, test } from "vitest";

import { getClientIdentity } from "./clientIdentity";

test("keeps one installation id and one tab id", () => {
  const persistent = new MemoryStorage();
  const firstTab = new MemoryStorage();
  const secondTab = new MemoryStorage();
  let next = 0;
  const randomUUID = () => `id-${++next}`;

  const first = getClientIdentity(persistent, firstTab, randomUUID);
  const restored = getClientIdentity(persistent, firstTab, randomUUID);
  const anotherTab = getClientIdentity(persistent, secondTab, randomUUID);

  assert.deepEqual(first, {
    clientId: "id-1",
    clientInstanceId: "id-2",
    persistent: true,
  });
  assert.deepEqual(restored, first);
  assert.equal(anotherTab.clientId, first.clientId);
  assert.notEqual(anotherTab.clientInstanceId, first.clientInstanceId);
});

class MemoryStorage implements Pick<Storage, "getItem" | "setItem"> {
  readonly #values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.#values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.#values.set(key, value);
  }
}
