import { describe, expect, it } from "vitest";

import { routes } from "./routes";

describe("route builders", () => {
  it("builds the agreed helper and handoff paths", () => {
    expect(routes.helperTask("incident-1", "helper-2")).toBe(
      "/incidents/incident-1/helpers/helper-2",
    );
    expect(routes.handoff("incident-1")).toBe("/incidents/incident-1/handoff");
  });

  it("encodes external identifiers as single path segments", () => {
    expect(routes.join("invite/with spaces")).toBe("/join/invite%2Fwith%20spaces");
  });
});
