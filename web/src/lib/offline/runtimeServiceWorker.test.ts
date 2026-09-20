/// <reference types="node" />

import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

import { describe, expect, it, vi } from "vitest";

type FetchListener = (event: {
  request: { method: string; mode: string; url: string };
  respondWith(response: Promise<Response>): void;
}) => void;

describe("runtime service worker", () => {
  it("returns a readable offline page when navigation and cache both miss", async () => {
    const listeners = new Map<string, (...args: never[]) => void>();
    const cacheMatch = vi.fn().mockResolvedValue(undefined);
    const script = readFileSync(
      new URL("../../../public/runtime-service-worker.js", import.meta.url),
      "utf8",
    );

    runInNewContext(script, {
      URL,
      Request,
      Response,
      caches: {
        keys: vi.fn().mockResolvedValue([]),
        match: cacheMatch,
        open: vi.fn(),
      },
      fetch: vi.fn().mockRejectedValue(new TypeError("network unavailable")),
      self: {
        addEventListener(type: string, listener: (...args: never[]) => void) {
          listeners.set(type, listener);
        },
        clients: { claim: vi.fn() },
        location: { origin: "https://example.test" },
        skipWaiting: vi.fn(),
      },
    });

    let responsePromise: Promise<Response> | undefined;
    const fetchListener = listeners.get("fetch") as FetchListener | undefined;
    fetchListener?.({
      request: {
        method: "GET",
        mode: "navigate",
        url: "https://example.test/incidents/demo/helpers/runner",
      },
      respondWith(response) {
        responsePromise = response;
      },
    });

    const response = await responsePromise;
    expect(response).toBeDefined();
    expect(response?.status).toBe(503);
    expect(response?.headers.get("content-type")).toBe("text/html; charset=utf-8");
    expect(await response?.text()).toContain("目前無法載入此頁");
    expect(cacheMatch).toHaveBeenCalledWith("/index.html", { ignoreVary: true });
  });
});
