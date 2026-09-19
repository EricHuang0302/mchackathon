const base = process.env.WEB_ORIGIN ?? "http://127.0.0.1:8080";
const check = (condition, message) => { if (!condition) throw new Error(message); };
const json = async (path, init = {}) => {
  const response = await fetch(base + path, init);
  const body = await response.json().catch(() => null);
  return { response, body };
};
const auth = (token) => ({ Authorization: `Bearer ${token}`, "Content-Type": "application/json" });

const health = await json("/healthz");
check(health.response.ok && health.body.status === "ok", "healthz failed");
const spa = await fetch(base + "/incidents/synthetic/handoff");
check(spa.ok && (await spa.text()).includes('id="root"'), "SPA fallback failed");

const owner = await json("/v1/sessions", { method: "POST" });
check(owner.response.status === 201, "owner session failed");
const outsider = await json("/v1/sessions", { method: "POST" });
const incidentId = crypto.randomUUID();
const clientId = crypto.randomUUID();
const incident = await json("/v1/incidents", { method: "POST", headers: auth(owner.body.sessionToken), body: JSON.stringify({ incidentId, primaryClientId: clientId, ruleVersion: "demo-v1" }) });
check(incident.response.status === 201, "incident creation failed");

const event = { eventId: crypto.randomUUID(), type: "action.reported", detail: { action: "synthetic_smoke" }, clientId, clientInstanceId: crypto.randomUUID(), clientSequence: 1, clientTime: new Date().toISOString(), authorityEpoch: 1, stateRevision: 0, modeRevision: 0, ruleVersion: "demo-v1" };
const first = await json(`/v1/incidents/${incidentId}/event-batches`, { method: "POST", headers: auth(owner.body.sessionToken), body: JSON.stringify({ events: [event] }) });
check(first.body.acknowledgements[0].status === "accepted", "event write failed");
const duplicate = await json(`/v1/incidents/${incidentId}/event-batches`, { method: "POST", headers: auth(owner.body.sessionToken), body: JSON.stringify({ events: [event] }) });
check(duplicate.body.acknowledgements[0].status === "duplicate", "duplicate was not idempotent");
const stale = { ...event, eventId: crypto.randomUUID(), clientSequence: 2 };
const staleResult = await json(`/v1/incidents/${incidentId}/event-batches`, { method: "POST", headers: auth(owner.body.sessionToken), body: JSON.stringify({ events: [stale] }) });
check(staleResult.body.acknowledgements[0].code === "stale_revision", "stale revision was not rejected");
const denied = await json(`/v1/incidents/${incidentId}/snapshot`, { headers: auth(outsider.body.sessionToken) });
check(denied.response.status === 403, "cross-incident read was not denied");
const timeline = await json(`/v1/incidents/${incidentId}/handoff/events`, { headers: auth(owner.body.sessionToken) });
check(timeline.response.ok && timeline.body.events.length === 1, "event readback failed");
console.log("local smoke passed: health, SPA fallback, sessions, incident, event, duplicate, stale revision, permission, readback");
