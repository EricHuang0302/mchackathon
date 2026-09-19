import { afterEach, describe, expect, it, vi } from "vitest";

import { getOrCreateSession, refreshSession } from "./session";

const storage = new Map<string, string>();
const sessionStorageMock = {
  getItem: (key: string) => storage.get(key) ?? null,
  setItem: (key: string, value: string) => storage.set(key, value),
  removeItem: (key: string) => storage.delete(key),
};

afterEach(() => {
  storage.clear();
  vi.unstubAllGlobals();
});

describe("browser sessions", () => {
  it("replaces an unexpired cached token after the server rejects it", async () => {
    vi.stubGlobal("sessionStorage", sessionStorageMock);
    storage.set("first-aid.primary.session.v1", JSON.stringify({
      sessionToken: "stale-token",
      expiresAt: new Date(Date.now() + 60_000).toISOString(),
    }));
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({
      sessionToken: "fresh-token",
      expiresAt: new Date(Date.now() + 60_000).toISOString(),
    }, { status: 201 })));

    expect((await getOrCreateSession("primary")).sessionToken).toBe("stale-token");
    expect((await refreshSession("primary")).sessionToken).toBe("fresh-token");
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
