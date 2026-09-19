import type { ShareScope } from "../../types/api";

const scopes = new Set<ShareScope>(["aed_runner", "ambulance_greeter", "ems_viewer"]);

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
