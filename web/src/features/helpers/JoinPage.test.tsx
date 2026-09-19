// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { ApiClientError } from "../../lib/connection/apiClient";
import { JoinPage } from "./JoinPage";
import { inviteFailureFor, parseInviteScope, taskForScope } from "./invitationCopy";

describe("JoinPage invitation copy", () => {
  it.each([
    ["aed_runner", "取得並送達 AED"],
    ["ambulance_greeter", "接應救護車"],
    ["ems_viewer", "查看救護交接資料"],
  ] as const)("shows the %s task", (scope, title) => {
    expect(taskForScope(parseInviteScope(`?scope=${scope}`)).title).toContain(title);
    expect(taskForScope(parseInviteScope(`?role=${scope}`)).title).toContain(title);
  });

  it("does not trust an unknown scope", () => {
    expect(parseInviteScope("?scope=primary")).toBeNull();
    expect(taskForScope(null).title).toBe("現場需要你協助");
  });

  it.each([
    ["invitation_expired", "expired", "expired"],
    ["invitation_redeemed", "expired", "redeemed"],
    ["invitation_revoked", "expired", "revoked"],
    ["permission_denied", "unauthorized", "permission_denied"],
  ] as const)("maps %s to its failure screen", (reason, code, expected) => {
    const error = new ApiClientError(403, {
      error: { code, message: "failure", requestId: "request", details: { reason } },
    });
    expect(inviteFailureFor(error)).toBe(expected);
  });
});

describe("JoinPage navigation", () => {
  let container: HTMLDivElement | undefined;
  let root: ReturnType<typeof createRoot> | undefined;

  afterEach(() => {
    if (root) act(() => root?.unmount());
    container?.remove();
    root = undefined;
    container = undefined;
  });

  it("clears the one-time secret fragment on mount", () => {
    history.replaceState(null, "", "/join/invite-1?scope=aed_runner#one-time-secret");
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);

    act(() => root?.render(
      <BrowserRouter>
        <Routes>
          <Route path="/join/:inviteId" element={<JoinPage />} />
          <Route path="/" element={<p>home</p>} />
        </Routes>
      </BrowserRouter>,
    ));

    expect(location.hash).toBe("");
    expect(container.textContent).toContain("協助取得並送達 AED");
  });

  it("opens a demo helper task without redeeming the demo secret", () => {
    history.replaceState(null, "", "/join/demo-aed-runner?role=aed_runner#demo-only");
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);

    act(() => root?.render(
      <BrowserRouter>
        <Routes>
          <Route path="/join/:inviteId" element={<JoinPage />} />
          <Route path="/incidents/:incidentId/helpers/:helperId" element={<p>helper task</p>} />
        </Routes>
      </BrowserRouter>,
    ));

    const accept = [...container.querySelectorAll("button")].find((button) => button.textContent === "接受任務");
    act(() => accept?.click());
    expect(location.pathname).toBe("/incidents/demo-incident/helpers/demo-helper");
    expect(container.textContent).toContain("helper task");
  });

  it("records a local decline for a demo invitation", () => {
    history.replaceState(null, "", "/join/demo-aed-runner");
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);

    act(() => root?.render(
      <BrowserRouter>
        <Routes>
          <Route path="/join/:inviteId" element={<JoinPage />} />
        </Routes>
      </BrowserRouter>,
    ));

    const decline = [...container.querySelectorAll("button")].find((button) => button.textContent === "我無法協助");
    act(() => decline?.click());
    expect(container.textContent).toContain("已回報無法協助");
  });
});
