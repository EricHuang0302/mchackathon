# Local API integration contract

The HTTP source of truth is [openapi.json](openapi.json), generated from
[schemas/contracts.py](app/schemas/contracts.py). All structured operations use
same-origin JSON REST. Only Gemini Live media and control use the dedicated
WebSocket. The browser must never connect directly to PostgreSQL.

## Authentication and call order

1. Render the 119 link immediately; session creation must not block it.
2. Call `POST /v1/sessions` with no body. The response includes `actorId`,
   `sessionToken`, and `expiresAt`. Hold the opaque token in the shared browser
   transport. Send it as `Authorization: Bearer <sessionToken>` on later HTTP
   calls. A new session alone does not grant incident access.
3. The primary calls `POST /v1/incidents` with stable `incidentId`,
   `primaryClientId`, and pinned `ruleVersion`. A retry with the same owner and
   payload returns the existing incident.
4. A helper or EMS viewer creates its own local session, then redeems a QR
   secret using `POST /v1/share-sessions`. The response gives `incidentId`,
   `scope`, optional `helperId`, and grant `expiresAt`. Continue using the
   invitee's own session token; there is no Firebase custom token.

Tokens and invitation secrets must stay out of logs and URL query parameters.
Share URLs can carry a secret in the fragment, which is not sent in the HTTP
request line. The backend stores token hashes and invite hashes, and encrypts
invite secrets needed for idempotent retries. Session expiry and grant expiry
are separate. An expired or revoked session returns `401`; an inaccessible
incident or expired grant returns `403`.

## REST routes and consumers

| Route | Consumer / permission | Purpose |
| --- | --- | --- |
| `POST /v1/sessions` | Any browser | Create an expiring local identity. |
| `POST /v1/incidents` | Authenticated primary | Idempotently register an incident. |
| `POST /v1/incidents/{id}/event-batches` | Primary | Upload ordered, revisioned events. |
| `POST /v1/incidents/{id}/scene-observations` | Primary | Add typed observations and advance snapshot revision. |
| `GET /v1/incidents/{id}/snapshot` | Primary, greeter, EMS | Read the canonical observations with provenance and revision. |
| `POST /v1/incidents/{id}/location-descriptions` | Primary | External geocoding adapter; currently `503`. |
| `POST /v1/incidents/{id}/shares` | Primary | Create expiring one-time runner, greeter, or EMS invitation. |
| `POST /v1/incidents/{id}/access-revocations` | Primary | Revoke all pending invitations and active grants with an expected state revision and idempotency key. |
| `POST /v1/share-sessions` | Invitee | Redeem invitation into a scoped local grant. |
| `POST /v1/incidents/{id}/helpers/{helperId}/updates` | Assigned helper | Report own status or foreground location with assignment revision. |
| `GET /v1/incidents/{id}/aeds` | Primary, runner | Return AED candidates; currently empty with unknown freshness. |
| `GET /v1/incidents/{id}/handoff/events` | Primary, EMS | Read sanitized paginated timeline. |
| `PATCH /v1/incidents/{id}` | Primary | Handover or close with expected state revision. |

A `POST /v1/incidents` example:

```json
{"incidentId":"11111111-1111-4111-8111-111111111111","primaryClientId":"22222222-2222-4222-8222-222222222222","ruleVersion":"demo-v1"}
```

An event batch contains `eventId`, `clientId`, `clientInstanceId`, monotonic
`clientSequence`, `clientTime`, `authorityEpoch`, `stateRevision`,
`modeRevision`, `ruleVersion`, `type`, and allowlisted `detail`. Store event IDs
in the offline outbox and retry them unchanged. Identical duplicates return
`duplicate`; altered duplicates, stale revisions, or unauthorized updates
return a per-event `conflict` with `code`. A `mode.changed` event carries the
next mode revision. The user reports call state; the browser cannot infer it.

`GET snapshot` returns `incidentId`, `snapshotRevision`,
`generatedThroughRevision`, and typed `observations`. Each observation carries
`key`, `value` (including `"unknown"`), `source`, `confirmation`,
`observedAt`, and evidence event IDs. Camera proposals are not confirmations.
Render the same snapshot in rescuer, greeter, and EMS views. A runner cannot
read it or the handoff timeline. The current snapshot is an observation list;
MIST and reviewed projection fields remain workstream 5 work.

REST errors use
`{"error":{"code":"stale_revision","message":"...","requestId":"...","details":{"stateRevision":2}}}`.
Codes include `invalid_input`, `unauthorized`, `expired`, `stale_revision`,
`rule_mismatch`, and `unavailable`. Responses are `Cache-Control: no-store`.

## Live WebSocket

Connect from `PUBLIC_ORIGIN` to `/v1/incidents/{id}/live`. The first JSON
message is:

```json
{
  "type": "auth",
  "token": "<local session token>",
  "envelope": {
    "protocolVersion": 1,
    "messageId": "55555555-5555-4555-8555-555555555555",
    "incidentId": "11111111-1111-4111-8111-111111111111",
    "clientId": "22222222-2222-4222-8222-222222222222",
    "clientInstanceId": "33333333-3333-4333-8333-333333333333",
    "clientSequence": 2,
    "clientTime": "2026-09-19T00:00:01Z",
    "authorityEpoch": 1,
    "stateRevision": 1,
    "modeRevision": 1,
    "payload": {"type": "session.hello"}
  }
}
```

Every connection and reconnection replies with authoritative revisions,
`voiceAllowed:false`, and `resumeRequired:true`. The browser reconciles REST
events and requires an explicit user action before `resume.request` in committed
`voice_guidance`. `mode.silence` immediately closes the provider. `media.frame`
requires an accepted resume and matching mode revision; PCM 16 kHz audio is
limited to 64 KiB decoded per frame. The current provider can emit only
`observation.proposed`; no Agent speech is implemented. Stale output must be
dropped by the browser audio gate even if the backend also rejects it.

## Remaining service boundaries

The PostgreSQL adapter currently reuses the validated synthetic state machine
for non-clinical event transitions and scope checks. It persists these through
one locked JSONB row, so it is intentionally sized for a small local demo.
Workstream 5 still supplies reviewed clinical rules, normalized projections,
AED ingestion and routing, geocoding, granular revocation controls, and scheduled retention
cleanup. Do not present empty AED results as a complete search. The frontend
foundation still shows static synthetic screens; workstreams 2–4 must wire the
shared API client, call-mode audio gate, and helper / handoff views.
