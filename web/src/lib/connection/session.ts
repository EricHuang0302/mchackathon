import { ApiClient } from "./apiClient";
import type { SessionResponse, ShareSessionResponse } from "../../types/api";
import { getClientIdentity } from "../offline/clientIdentity";

const canStore = () => typeof sessionStorage !== "undefined";
const read = <T>(key: string): T | null => {
  if (!canStore()) return null;
  try { return JSON.parse(sessionStorage.getItem(key) ?? "null") as T | null; } catch { return null; }
};
const write = (key: string, value: unknown) => { if (canStore()) sessionStorage.setItem(key, JSON.stringify(value)); };

export const getOrCreateSession = async (namespace: "primary" | "participant") => {
  const key = `first-aid.${namespace}.session.v1`;
  const existing = read<SessionResponse>(key);
  if (existing && new Date(existing.expiresAt).getTime() > Date.now()) return existing;
  const created = await new ApiClient().createSession();
  write(key, created);
  return created;
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
export const clearIncidentSession = () => {
  if (!canStore()) return;
  ["first-aid.primary.session.v1", "first-aid.primary.identity.v1", "first-aid.primary.outbox.v1", "first-aid.participant.session.v1", "first-aid.participant.grant.v1"].forEach((key) => sessionStorage.removeItem(key));
};
