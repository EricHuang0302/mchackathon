import { describe, expect, it } from "vitest";

import { DEMO_TIMELINE_STORAGE_KEY, loadDemoTimeline, saveDemoTimeline } from "./demoTimeline";

function memoryStorage(initial?: string) {
  const values = new Map<string, string>();
  if (initial !== undefined) values.set(DEMO_TIMELINE_STORAGE_KEY, initial);
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); },
  };
}

describe("demo timeline storage", () => {
  it("round-trips shared demo events", () => {
    const storage = memoryStorage();
    const timeline = [{ id: "event-1", type: "CPR_STARTED", timestamp: "2026-09-19T12:00:00Z", note: "開始按壓" }];
    saveDemoTimeline(timeline, storage);
    expect(loadDemoTimeline(storage)).toEqual(timeline);
  });

  it("rejects malformed stored data", () => {
    expect(loadDemoTimeline(memoryStorage('{"not":"events"}'))).toBeNull();
  });
});
