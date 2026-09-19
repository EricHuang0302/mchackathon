import type { TimelineEvent } from "../../types/rescue";

export const DEMO_TIMELINE_STORAGE_KEY = "first-aid-copilot.demo-timeline.v1";

type TimelineStorage = Pick<Storage, "getItem" | "setItem">;

export function loadDemoTimeline(storage: TimelineStorage = window.localStorage): TimelineEvent[] | null {
  const raw = storage.getItem(DEMO_TIMELINE_STORAGE_KEY);
  if (raw === null) return null;
  try {
    const value: unknown = JSON.parse(raw);
    return Array.isArray(value) && value.every(isTimelineEvent) ? value : null;
  } catch {
    return null;
  }
}

export function saveDemoTimeline(
  timeline: TimelineEvent[],
  storage: TimelineStorage = window.localStorage,
): void {
  storage.setItem(DEMO_TIMELINE_STORAGE_KEY, JSON.stringify(timeline));
}

function isTimelineEvent(value: unknown): value is TimelineEvent {
  if (!value || typeof value !== "object") return false;
  const event = value as Partial<TimelineEvent>;
  return typeof event.id === "string"
    && typeof event.type === "string"
    && typeof event.timestamp === "string"
    && (event.note === undefined || typeof event.note === "string");
}
