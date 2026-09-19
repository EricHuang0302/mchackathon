import { describe, expect, it } from "vitest";

import { ApiClientError } from "../../lib/connection/apiClient";
import { aedEstimate, formatDistance, formatEta, inviteUnavailableReason, isTimestampStale } from "./helperPresentation";

describe("helper presentation", () => {
  it("distinguishes walking routes from straight-line estimates", () => {
    expect(aedEstimate({
      aedId: "aed-1",
      name: "Library",
      latitude: 25.0,
      longitude: 121.5,
      address: "測試地址 1",
      availability: "available",
      straightLineMeters: 240,
      walkingMeters: 360,
      etaSeconds: 245,
      routeUpdatedAt: "2026-09-19T10:00:00Z",
      estimateSource: "route",
    }, new Date("2026-09-19T10:00:30Z").getTime())).toEqual({
      distanceLabel: "步行 360 公尺",
      etaLabel: "5 分鐘",
      sourceLabel: "步行路線估算",
      stale: false,
    });

    expect(aedEstimate({
      aedId: "aed-2",
      name: "Gym",
      latitude: 25.1,
      longitude: 121.6,
      address: "測試地址 2",
      availability: "unknown",
      straightLineMeters: 1_250,
      walkingMeters: 1_500,
      etaSeconds: 900,
      estimateSource: "straight_line",
    })).toMatchObject({
      distanceLabel: "直線 1.3 公里",
      etaLabel: null,
      sourceLabel: "直線距離參考",
    });
  });

  it("formats conservative distance, ETA, and freshness labels", () => {
    expect(formatDistance(180)).toBe("180 公尺");
    expect(formatEta(61)).toBe("2 分鐘");
    expect(isTimestampStale("2026-09-19T10:00:00Z", new Date("2026-09-19T10:03:00Z").getTime())).toBe(true);
    expect(isTimestampStale(null)).toBe(false);
  });

  it("recognizes an expired one-time invitation", () => {
    const error = new ApiClientError(403, {
      error: { code: "expired", message: "expired", requestId: "request-1" },
    });
    expect(inviteUnavailableReason(error)).toBe("expired_or_used");
    expect(inviteUnavailableReason(new Error("network"))).toBeNull();
  });
});
