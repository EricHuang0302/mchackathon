import { ApiClient } from "./apiClient";
import type { SessionResponse, ShareSessionResponse } from "../../types/api";
import { getClientIdentity } from "../offline/clientIdentity";

const canStore = () => typeof sessionStorage !== "undefined";
const read = <T>(key: string): T | null => {
  if (!canStore()) return null;
  try { return JSON.parse(sessionStorage.getItem(key) ?? "null") as T | null; } catch { return null; }
};
const write = (key: string, value: unknown) => { if (canStore()) sessionStorage.setItem(key, JSON.stringify(value)); };
const sessionKey = (namespace: "primary" | "participant") => `first-aid.${namespace}.session.v1`;

export const getOrCreateSession = async (namespace: "primary" | "participant") => {
  const key = sessionKey(namespace);
  const existing = read<SessionResponse>(key);
  if (existing && new Date(existing.expiresAt).getTime() > Date.now()) return existing;
  const created = await new ApiClient().createSession();
  write(key, created);
  return created;
};

export const refreshSession = async (namespace: "primary" | "participant") => {
  if (canStore()) sessionStorage.removeItem(sessionKey(namespace));
  return getOrCreateSession(namespace);
};

export interface PrimaryIdentity { incidentId: string; clientId: string; clientInstanceId: string; ruleVersion: string }
export const getPrimaryIdentity = (): PrimaryIdentity => {
  const key = "first-aid.primary.identity.v1";
  const existing = read<Omit<PrimaryIdentity, "clientInstanceId">>(key);
  const browserIdentity = getClientIdentity();
  const stable = existing ?? { incidentId: crypto.randomUUID(), clientId: browserIdentity.clientId, ruleVersion: "demo-v1" };
  if (!existing) write(key, stable);
  return { ...stable, clientInstanceId: browserIdentity.clientInstanceId };
};

export const saveParticipantGrant = (grant: ShareSessionResponse) => write("first-aid.participant.grant.v1", grant);
export const getParticipantGrant = () => read<ShareSessionResponse>("first-aid.participant.grant.v1");
export interface ParticipantTaskProgress {
  incidentId: string;
  helperId: string;
  assignmentRevision: number;
  status: string;
}
export const saveParticipantTaskProgress = (progress: ParticipantTaskProgress) =>
  write("first-aid.participant.task.v1", progress);
export const getParticipantTaskProgress = () =>
  read<ParticipantTaskProgress>("first-aid.participant.task.v1");
export interface AedRunnerHelper { incidentId: string; helperId: string }
export const saveAedRunnerHelper = (helper: AedRunnerHelper) =>
  write("first-aid.primary.aed-runner.v1", helper);
export const getAedRunnerHelper = () => read<AedRunnerHelper>("first-aid.primary.aed-runner.v1");

export const clearIncidentSession = () => {
  if (!canStore()) return;
  ["first-aid.primary.session.v1", "first-aid.primary.identity.v1", "first-aid.primary.outbox.v1", "first-aid.participant.session.v1", "first-aid.participant.grant.v1", "first-aid.participant.task.v1", "first-aid.primary.aed-runner.v1"].forEach((key) => sessionStorage.removeItem(key));
};
