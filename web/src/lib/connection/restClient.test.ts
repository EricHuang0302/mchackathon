import { assert, expect, test } from "vitest";

import { ApiError, RestClient } from "./restClient";

test("adds authentication and serializes JSON", async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const client = new RestClient({
    baseUrl: "https://example.test/",
    getToken: async () => "token",
    fetchImpl: async (input, init) => {
      calls.push({ url: String(input), init });
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    },
  });

  const result = await client.request<{ ok: boolean }>("POST", "/events", {
    body: { value: 1 },
  });

  assert.deepEqual(result, { ok: true });
  assert.equal(calls.length, 1);
  assert.equal(calls[0]!.url, "https://example.test/events");
  assert.equal(new Headers(calls[0]!.init?.headers).get("Authorization"), "Bearer token");
  assert.equal(calls[0]!.init?.body, JSON.stringify({ value: 1 }));
});

test("maps API errors without retrying mutations", async () => {
  let calls = 0;
  const client = new RestClient({
    baseUrl: "https://example.test",
    fetchImpl: async () => {
      calls++;
      return new Response(
        JSON.stringify({
          error: { code: "stale_revision", message: "Revision is stale" },
        }),
        { status: 409 },
      );
    },
  });

  await expect(client.request("PATCH", "/incident", { body: {} })).rejects.toMatchObject({
    status: 409,
    code: "stale_revision",
    retryable: false,
  } satisfies Partial<ApiError>);
  assert.equal(calls, 1);
});
