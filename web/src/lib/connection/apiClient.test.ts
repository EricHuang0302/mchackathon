import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClient, ApiClientError, userMessageForApiError } from "./apiClient";

describe("ApiClient", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("binds the browser fetch receiver for default API requests", async () => {
    const fetcher = vi.fn(function (this: typeof globalThis) {
      expect(this).toBe(globalThis);
      return Promise.resolve(Response.json({ actorId: "actor", sessionToken: "token", expiresAt: "2099-01-01T00:00:00Z" }, { status: 201 }));
    });
    vi.stubGlobal("fetch", fetcher);

    await new ApiClient().createSession();

    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("uses same-origin paths and bearer authentication", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ candidates: [], dataUpdatedAt: null }), { status: 200, headers: { "Content-Type": "application/json" } }));
    await new ApiClient("secret", fetcher as typeof fetch).getAeds("incident-id");
    const [path, init] = (fetcher.mock.calls as unknown as Array<[string, RequestInit]>)[0]!;
    expect(path).toBe("/v1/incidents/incident-id/aeds?limit=10");
    expect((init.headers as Headers).get("Authorization")).toBe("Bearer secret");
  });

  it.each([
    [401, "登入已失效"], [403, "沒有權限"], [409, "資料版本已更新"], [503, "目前無法使用"],
  ])("maps status %s to a user-facing error", async (status, message) => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ error: { code: status === 409 ? "stale_revision" : status === 503 ? "unavailable" : "unauthorized", message: "failure", requestId: "request" } }), { status, headers: { "Content-Type": "application/json" } }));
    const error = await new ApiClient("token", fetcher as typeof fetch).getSnapshot("id").catch((reason) => reason);
    expect(error).toBeInstanceOf(ApiClientError);
    expect(userMessageForApiError(error)).toContain(message);
  });
});
