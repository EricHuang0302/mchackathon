import type { ShareScope } from "../../types/api";

const scopes = new Set<ShareScope>(["aed_runner", "ambulance_greeter", "ems_viewer"]);

const demoInviteIds: Record<ShareScope, string> = {
  aed_runner: "demo-aed-runner",
  ambulance_greeter: "demo-ambulance-greeter",
  ems_viewer: "demo-ems-viewer",
};

export function demoInviteId(scope: ShareScope) {
  return demoInviteIds[scope];
}

export function demoInviteScope(inviteId?: string): ShareScope | null {
  if (!inviteId) return null;
  return (Object.entries(demoInviteIds).find(([, id]) => id === inviteId)?.[0] as ShareScope | undefined) ?? null;
}

export function buildShareUrl(origin: string, inviteId: string, secret: string, scope: ShareScope) {
  const url = new URL(`/join/${encodeURIComponent(inviteId)}`, origin);
  url.searchParams.set("role", scope);
  url.hash = secret;
  return url.toString();
}

export function readScopeHint(search: string): ShareScope | null {
  const value = new URLSearchParams(search).get("role") as ShareScope | null;
  return value && scopes.has(value) ? value : null;
}

export function readInviteSecret(hash: string) {
  return hash.startsWith("#") ? hash.slice(1) : hash;
}
