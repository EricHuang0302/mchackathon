import type {
  Coordinates,
  DataFreshness,
  HelperRole,
  HelperTaskStatus,
  TimelineEvent,
} from "../../types/domain";

export interface TaskDestination {
  id: string;
  name: string;
  address: string;
  accessNote: string;
  coordinates: Coordinates;
  distanceMeters: number;
  walkingMinutes: number;
  availability?: string;
}

export interface SceneSnapshot {
  location: string;
  situation: string;
  treatment: string;
  entrance: string;
  updatedAt: string;
}

export interface HelperTask {
  id: string;
  incidentId: string;
  role: HelperRole;
  status: HelperTaskStatus;
  assignmentRevision: number;
  expiresAt: string;
  freshness: DataFreshness;
  destination: TaskDestination;
  scene: TaskDestination;
  snapshot: SceneSnapshot;
  timeline: TimelineEvent[];
}

export interface MistItem {
  letter: "M" | "I" | "S" | "T";
  label: string;
  value: string;
  confirmed: boolean;
}
