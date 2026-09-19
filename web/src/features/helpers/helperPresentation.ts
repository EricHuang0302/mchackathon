import type { AedListResponse } from "../../types/api";
import { ApiClientError } from "../../lib/connection/apiClient";

export type InviteUnavailableReason = "expired_or_used" | "missing_secret";

export function inviteUnavailableReason(error: unknown): InviteUnavailableReason | null {
  return error instanceof ApiClientError && error.code === "expired"
    ? "expired_or_used"
    : null;
}

export function formatDistance(meters: number) {
  if (meters < 1_000) return `${Math.round(meters)} 公尺`;
  return `${(meters / 1_000).toFixed(meters < 10_000 ? 1 : 0)} 公里`;
}

export function formatEta(seconds: number) {
  const minutes = Math.max(1, Math.ceil(seconds / 60));
  return `${minutes} 分鐘`;
}

export function formatSyncTime(value: string) {
  return new Intl.DateTimeFormat("zh-TW", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

export function isTimestampStale(value: string | null | undefined, now = Date.now(), thresholdMs = 120_000) {
  if (!value) return false;
  const timestamp = new Date(value).getTime();
  return !Number.isFinite(timestamp) || now - timestamp > thresholdMs;
}

export function aedEstimate(candidate: AedListResponse["candidates"][number], now = Date.now()) {
  const hasWalkingRoute = candidate.estimateSource === "route" && candidate.walkingMeters != null;
  return {
    distanceLabel: hasWalkingRoute
      ? `步行 ${formatDistance(candidate.walkingMeters!)}`
      : `直線 ${formatDistance(candidate.straightLineMeters)}`,
    etaLabel: hasWalkingRoute && candidate.etaSeconds != null ? formatEta(candidate.etaSeconds) : null,
    sourceLabel: candidate.estimateSource === "route"
      ? "步行路線估算"
      : candidate.estimateSource === "straight_line"
        ? "直線距離參考"
        : "尚無路線估算",
    stale: isTimestampStale(candidate.routeUpdatedAt, now),
  };
}
