import { describe, expect, it } from "vitest";

import { buildShareUrl, demoInviteId, demoInviteScope, readInviteSecret, readScopeHint } from "./shareLinks";

describe("helper share links", () => {
  it("keeps the secret in the URL fragment", () => {
    const url = new URL(buildShareUrl("https://救援.example", "invite id", "private-secret", "aed_runner"));

    expect(url.pathname).toBe("/join/invite%20id");
    expect(url.searchParams.get("role")).toBe("aed_runner");
    expect(url.hash).toBe("#private-secret");
    expect(url.search).not.toContain("private-secret");
  });

  it("accepts only known display hints", () => {
    expect(readScopeHint("?role=ems_viewer")).toBe("ems_viewer");
    expect(readScopeHint("?role=primary")).toBeNull();
    expect(readInviteSecret("#one-time-secret")).toBe("one-time-secret");
  });

  it("maps every demo role to a stable invitation route", () => {
    expect(demoInviteScope(demoInviteId("aed_runner"))).toBe("aed_runner");
    expect(demoInviteScope(demoInviteId("ambulance_greeter"))).toBe("ambulance_greeter");
    expect(demoInviteScope(demoInviteId("ems_viewer"))).toBe("ems_viewer");
    expect(demoInviteScope("not-a-demo-invite")).toBeNull();
  });
});
