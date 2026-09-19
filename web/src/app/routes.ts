const segment = (value: string) => encodeURIComponent(value);

export const routePatterns = {
  home: "/",
  join: "/join/:inviteId",
  helperTask: "/incidents/:incidentId/helpers/:helperId",
  handoff: "/incidents/:incidentId/handoff",
} as const;
export const routes = {
  home: routePatterns.home,
  join: (inviteId: string) => `/join/${segment(inviteId)}`,
  helperTask: (incidentId: string, helperId: string) =>
    `/incidents/${segment(incidentId)}/helpers/${segment(helperId)}`,
  handoff: (incidentId: string) => `/incidents/${segment(incidentId)}/handoff`,
} as const;
