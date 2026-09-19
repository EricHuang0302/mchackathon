# Backend integration guide

This file describes the API that **runs now** for the rescuer, browser runtime,
helper, and handoff workstreams. The checked HTTP source of truth is
[openapi.json](openapi.json), generated from
[app/schemas/contracts.py](app/schemas/contracts.py). The Live WebSocket contract
is described below. The frontend now has a shared same-origin REST client,
session/outbox runtime, Live client, and local audio gate. Narrative rescue
screens remain synthetic; the backend now projects canonical scene snapshots and MIST. The bundled rules still need clinical review.

## Where to connect

| Caller | Base URL | Notes |
| --- | --- | --- |
| Browser through the user's host Nginx | Same origin: `/v1/...` and `wss://<site>/v1/...` | Use the browser's current origin; Nginx must forward the path unchanged and pass WebSocket Upgrade. |
| Command line on the Docker host | `http://127.0.0.1:<API_PORT>` | `API_PORT` defaults to `8000` and is configurable in root `.env`. This loopback URL is not a phone URL. |
| PostgreSQL | No browser or host endpoint | Only the API container connects to `db:5432` inside Compose. |

Compose starts `web`, `api`, `db`, a one-shot `migrate` job, and an hourly
`retention` job. Nginx is configured and run by the project owner on the
host's ports 80/443. The web container serves the Vite production
build with SPA fallback. Host Nginx sends ordinary pages to
`127.0.0.1:<WEB_PORT>` and proxies `/v1/` and `/healthz` to
`127.0.0.1:<API_PORT>`. The API expects the `/v1`
prefix to be preserved. Set `PUBLIC_ORIGIN` in `.env` to the **exact** browser
origin, including scheme and any nonstandard port. Browser WebSocket requests
with another `Origin` are closed. Same-origin REST needs no CORS setup; a
separate development origin must be listed in `ALLOWED_ORIGINS` if the API is
run outside Compose. Use trusted HTTPS for phone microphone/camera access.

`GET /healthz` needs no token and returns `{"status":"ok"}`. It checks the
Flask process, not PostgreSQL or external providers. A host-side smoke check:

```sh
API="http://127.0.0.1:8000" # replace 8000 with API_PORT from .env
curl -i "$API/healthz"
curl -i -X POST "$API/v1/sessions"
```

All HTTP responses have `Cache-Control: no-store`. JSON request bodies are
limited to 1 MiB.

## Identity and access sequence

1. Show the 119 link immediately. Authentication, GPS, and model startup must
   never delay it.
2. Call `POST /v1/sessions` with no body. It returns `201` with `actorId`, an
   opaque `sessionToken`, and `expiresAt` (12 hours from creation). For example:

   ```json
   {"actorId":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","sessionToken":"<opaque token>","expiresAt":"2026-09-19T12:00:00Z"}
   ```

3. Send `Authorization: Bearer <sessionToken>` on every other `/v1` HTTP call.
   The browser sends the token in the **first WebSocket JSON message**, because
   the browser WebSocket API cannot set an Authorization header.
4. A primary session registers its own incident. Helpers and EMS viewers create
   **their own** local session before redeeming a share secret. Redeeming a
   share binds a scoped grant to that existing actor; it does not return a new
   token or change the actor's identity.

A new session has no access to an existing incident, even if it knows its ID.
Keep the primary token available for the intended browser refresh lifecycle;
losing it does not automatically transfer ownership to a new actor. Do not put
session tokens or share secrets in logs, URL query strings, or `VITE_*` values.
A share link can put its secret in the URL fragment; the invitee sends it in
the `POST /v1/share-sessions` JSON body. The server stores token hashes and
invite lookup hashes; retry copies of invite secrets are encrypted at rest.

## Implemented HTTP routes

`{id}` is an incident UUID; `{helperId}` is a helper UUID. All paths below are
relative to the browser's same origin. Only `/v1/sessions` and `/healthz` are
unauthenticated.

| Method and path | Allowed actor | Current result |
| --- | --- | --- |
| `POST /v1/sessions` | Any caller | Create an expiring local actor and token. |
| `POST /v1/incidents` | Authenticated actor | Register an incident owned by that actor; identical retries return the existing incident. |
| `POST /v1/incidents/{id}/event-batches` | Primary | Append ordered reports; each event returns `accepted`, `duplicate`, or `conflict`. |
| `POST /v1/incidents/{id}/scene-observations` | Primary | Store typed observations using `expectedSnapshotRevision` and `idempotencyKey`. |
| `POST /v1/incidents/{id}/scene-image-analyses` | Primary | Analyze one bounded JPEG/WebP using `expectedModeRevision`; returns unconfirmed camera proposals and does not retain the frame. |
| `GET /v1/incidents/{id}/snapshot` | Primary, ambulance greeter, EMS viewer | Read the same revisioned scene sections, actions, and observations. AED runners are denied. |
| `POST /v1/incidents/{id}/location-descriptions` | Primary | Validates coordinates, then returns `503 unavailable`; geocoding is not connected. |
| `POST /v1/incidents/{id}/shares` | Primary | Create a one-time invitation with a 60–3600 second expiry. |
| `POST /v1/share-sessions` | Authenticated invitee | Redeem a secret into a scoped grant bound to the invitee's actor. |
| `POST /v1/incidents/{id}/access-revocations` | Primary | Revoke **all** pending invitations and active grants for this incident; no per-person revoke yet. |
| `POST /v1/incidents/{id}/helpers/{helperId}/updates` | Assigned runner or greeter | Update only that helper's status/location using `updateId` and `expectedAssignmentRevision`. |
| `GET /v1/incidents/{id}/aeds?limit=10` | Primary, AED runner | Search the imported active AED catalog around the canonical location or supplied `lat`/`lng`; returns an empty list until a dataset is imported. |
| `GET /v1/incidents/{id}/handoff/events?limit=25&cursor=...` | Primary, EMS viewer | Paginated timeline; EMS event details are filtered. Greeters and runners are denied. |
| `GET /v1/incidents/{id}/handoff?limit=25&cursor=...` | Primary, EMS viewer | Canonical snapshot, evidence-backed MIST, and sanitized timeline page from one read model. |
| `POST /v1/incidents/{id}/rule-evaluations` | Primary | Evaluate the pinned Python rules at exact state/mode revisions. Demo rules require the explicit unreviewed-demo switch. |
| `POST /v1/incidents/{id}/aed-assignments` | Primary | Assign an AED to a currently granted runner using a known patient location and imported catalog. |
| `POST /v1/incidents/{id}/helpers/{helperId}/aed-unavailability-reports` | Assigned runner | Exclude an unavailable AED and return the revised destination or an explicit no-candidate result. |
| `PATCH /v1/incidents/{id}` | Primary | Set `handed_over` or `closed` using `expectedStateRevision`. |

A route appearing in OpenAPI does not imply external data is available. There is no current REST endpoint to read a complete helper assignment list,
walking route, or geocoded address. Rule evaluation is a preview and does not
commit a clinical state transition. Do not invent unavailable data in a frontend feature. API route and model changes must update OpenAPI and the
shared frontend transport types together.

## Primary rescuer and browser runtime

Register the incident after acquiring a session. The browser generates and
retains the two UUIDs, and pins one `ruleVersion` for the incident:

```http
POST /v1/incidents
Authorization: Bearer <sessionToken>
Content-Type: application/json

{"incidentId":"11111111-1111-4111-8111-111111111111","primaryClientId":"22222222-2222-4222-8222-222222222222","ruleVersion":"demo-v1"}
```

The response is an `IncidentView` containing `status`, `interactionMode`,
`stateRevision`, `modeRevision`, `snapshotRevision`, `authorityEpoch`, and
`createdAt`. A new incident starts in `call_119` with state/mode/snapshot
revisions `0` and authority epoch `1`. Preserve these fields across REST and
Live messages.

The browser must close its **local audio gate immediately** when the user starts
a call and first upload `call.reported` with `reportedState:"attempted"`; opening
the configured telephone link does not control the phone or prove the call
connected. Only an explicit user confirmation uploads the following mode report.
A `mode.changed` event carries the **next** `modeRevision`, while `stateRevision`
is the current committed value:

```json
{
  "events": [{
    "eventId": "44444444-4444-4444-8444-444444444444",
    "type": "mode.changed",
    "detail": {"interactionMode":"on_call","reason":"dispatcher_reported_active"},
    "clientId": "22222222-2222-4222-8222-222222222222",
    "clientInstanceId": "33333333-3333-4333-8333-333333333333",
    "clientSequence": 1,
    "clientTime": "2026-09-19T00:00:00Z",
    "authorityEpoch": 1,
    "stateRevision": 0,
    "modeRevision": 1,
    "ruleVersion": "demo-v1"
  }]
}
```

The currently accepted mode changes are:

| Current mode | Reported reason | Next mode |
| --- | --- | --- |
| `call_119` | `dial_started` or `dispatcher_reported_active` | `on_call` |
| `call_119` | `user_reports_call_failed` | `voice_guidance` |
| `on_call` | `user_reports_call_ended_or_failed` | `voice_guidance` |
| `voice_guidance` | `dial_started` or `dispatcher_reported_active` | `on_call` |
| `call_119`, `on_call`, or `voice_guidance` | `user_reports_ems_arrived` | `handover` |

These are user/browser reports, not telephone-state detection. A `call.reported`
event requires `detail.source:"user"` and a `reportedState` of `attempted`,
`active`, `ended`, `failed`, or `uncertain`.

A successful batch returns `acknowledgements` plus authoritative revisions and
`lastAcknowledgedClientSequence`. HTTP `200` can still contain a per-event
`conflict`; inspect each acknowledgement. Keep `eventId` and payload unchanged
on retry: an identical duplicate returns `duplicate`, while a reused ID with
different content returns `conflict`. Within a `clientInstanceId`, increment
`clientSequence`; store client occurrence time separately from the returned
server receipt time. Only a clinical state transition advances `stateRevision`; mode changes advance
`modeRevision` separately. Use the returned revisions as authoritative. Currently
accepted types are `mode.changed`, `call.reported`, `action.reported`,
`event.corrected`, `observation.proposed`, `observation.confirmed`,
`command.acknowledged`, `timer.elapsed`, and `helper.updated`; see `EventInput`
for the allowlisted `detail` fields. A button tap reports an action and does
not prove clinical treatment occurred.

For observations, send an `idempotencyKey` UUID, the current
`expectedSnapshotRevision`, and 1–20 `ObservationInput` entries. For example:

```json
{"expectedSnapshotRevision":0,"idempotencyKey":"99999999-9999-4999-8999-999999999999","observations":[{"observationId":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","key":"breathing_reported","value":"unknown","source":"manual_report","observedAt":"2026-09-19T00:00:02Z","confirmation":"uncertain","evidenceEventIds":[]}]}
```

Each entry has `observationId`, `key`, `value`, `source`, `observedAt`, `confirmation`, and
`evidenceEventIds`. Preserve `"unknown"` as unknown. A camera proposal cannot
confirm itself. Read `GET /v1/incidents/{id}/snapshot` for the canonical
`incidentId`, `snapshotRevision`, `generatedThroughRevision`,
`sections`, `actionsPerformed`, and provenance-bearing observations. MIST is
available from `/handoff`, not the snapshot endpoint. A stale snapshot revision returns HTTP `409`.

### Scene image analysis

`POST /v1/incidents/{id}/scene-image-analyses` accepts JSON with `imageBase64`,
`mimeType` (`image/jpeg` or `image/webp`), `capturedAt`, and
`expectedModeRevision`. The decoded image is limited to 700 KB and its file
signature must match the declared MIME type. Only the primary incident session
may call the endpoint. Closed, handed-over, or stale-mode requests fail before
the provider is invoked.

The response contains exactly five `camera_proposal` observations:
`hazards.traffic`, `hazards.fire`, `hazards.standingWater`, `hazards.crowd`, and
`patient.bleeding`. Hazard values are `true`, `false`, or `"unknown"`;
bleeding values are `none`, `minor`, `severe`, `life_threatening`, or
`unknown`. Every result remains `proposed` until the browser submits a separate
human-confirmed `manual_report`. The browser also derives `hazards.present`
from the four reviewed hazard answers. Raw image bytes are not written to the
event store, database, or ordinary logs.

## Helpers, sharing, and handoff

The primary creates a share with `scope` equal to `aed_runner`,
`ambulance_greeter`, or `ems_viewer`. Runner/greeter requests require
`helperId`; EMS requests must omit it. For example:

```json
{"scope":"aed_runner","helperId":"66666666-6666-4666-8666-666666666666","expiresInSeconds":300,"idempotencyKey":"77777777-7777-4777-8777-777777777777"}
```

The response contains `inviteId`, a high-entropy `secret`, `scope`, and
`expiresAt`. A new invitee first creates its own session, then sends
`{"secret":"<share secret>"}` to `POST /v1/share-sessions` with its Bearer token.
The `201` response contains `incidentId`, `scope`, nullable `helperId`, and
grant `expiresAt`; keep using the invitee's original token. Invitations can be
redeemed once. Reusing the share-creation `idempotencyKey` with the same
payload returns the original invitation; changing the payload returns `409`.
Failed redemption keeps the existing top-level `expired` or `unauthorized`
code and adds `error.details.reason`: `invitation_expired`,
`invitation_redeemed`, `invitation_revoked`, or `permission_denied`. Unknown
secrets use `invitation_expired` so the response does not reveal whether an
invitation ever existed.

An assigned helper sends an `updateId` UUID, current
`expectedAssignmentRevision`, `reportedAt`, and either `status` or both `lat`
and `lng`. `locationAccuracyMeters` is optional. The implemented statuses are
`accepted`, `en_route`, `arrived`, `obtained`, and `unavailable`. A successful
first update returns `assignmentRevision:1`; identical `updateId` retries
return the original response. This generic status update records a helper event; use the dedicated
`aed-unavailability-reports` endpoint to trigger AED reassignment. There is no
complete helper-list read endpoint or measured route ETA.

The primary may revoke every pending invitation and active grant with:

```json
{"expectedStateRevision":2,"idempotencyKey":"88888888-8888-4888-8888-888888888888"}
```

Send this body to `POST /v1/incidents/{id}/access-revocations`. The response
contains the new `stateRevision`, `revokedInvitations`, and `revokedGrants`.
The revocation is idempotent for the same key and body. `PATCH /v1/incidents/{id}`
with `{"status":"closed","expectedStateRevision":3}` closes an incident and
removes existing grants. Closing also revokes unredeemed invitations and active grants. A closed incident
also denies new primary mutations. Do not present a QR scan as EMS takeover.

The greeter and EMS viewer may read the same snapshot. EMS may additionally
read `/handoff/events`; the response includes `snapshotRevision`,
`generatedThroughRevision`, `events`, and an opaque `nextCursor` (or `null`).
Pass `nextCursor` unchanged for the next page. Event entries contain `eventId`,
`type`, `clientTime`, `serverTime`, and `detail`. Read `/handoff` for the
canonical snapshot above the evidence-backed MIST and timeline from the same
read model. The EMS detail filter removes fields outside
a small allowlist; do not reconstruct hidden information from another source.

## Rules, AED reassignment, and canonical handoff

The backend rule endpoint evaluates an incident's **pinned** rule package with
exact `expectedStateRevision` and `expectedModeRevision`; it returns a decision
preview and does not commit a state transition. Example body:

```json
{"expectedStateRevision":0,"expectedModeRevision":0,"trigger":{"type":"observation"},"observations":[],"timers":[]}
```

The response includes `ruleVersion`, `contentHash`, `reviewStatus`,
`clinicalReviewRequired`, and `decision`. `demo-v1` is `unreviewed_demo` and
returns `503` unless the backend has `ENABLE_UNREVIEWED_DEMO_RULES=1` for a
synthetic training demonstration. Consumers must not present that result as
clinically approved guidance.

Import an AED dataset using [the AED data procedure](../data/aed/README.md).
For `GET /v1/incidents/{id}/aeds`, supply `lat` and `lng` together or first
record `location.coordinates` as a scene observation with
`{"latitude":25.033,"longitude":121.565}`. Without either, candidates are
empty. The primary may dispatch only to a helper who has already redeemed an
active `aed_runner` grant:

```http
POST /v1/incidents/{id}/aed-assignments
Content-Type: application/json

{"helperId":"66666666-6666-4666-8666-666666666666","expectedStateRevision":0}
```

A runner who cannot obtain the assigned AED uses the dedicated endpoint,
with the assigned `aedId` and current `assignmentRevision`:

```http
POST /v1/incidents/{id}/helpers/{helperId}/aed-unavailability-reports
Content-Type: application/json

{"reportId":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb","aedId":"synthetic-aed-1","reasonCode":"cabinet_locked","expectedAssignmentRevision":1,"reportedAt":"2026-09-19T00:00:00Z"}
```

Both responses include `outcome`, nullable `aedId`, nullable
`assignmentRevision`, `previousAedId`, `excludedAedIds`, `deduplicated`, and
nullable `estimate`. An unavailable report is idempotent by `reportId`; retry
the **same** body. `stale_revision` returns HTTP `409`; a report for another
AED is denied. `no_candidate` means no known accessible destination. When no
walking-route provider is configured, the estimate explicitly uses a
straight-line fallback with uncertainty; it is not walking navigation or ETA.
The generic helper `status:"unavailable"` update records a report but does not
reassign an AED.

`GET /v1/incidents/{id}/handoff` returns `snapshot`, `mist`, and a `timeline`
page in one response; pass `timeline.nextCursor` unchanged to the next call.
`mist.snapshotRevision` matches the canonical snapshot. Only primary and EMS
sessions can read it. The greeter reads `/snapshot` only, while the runner
cannot read either clinical resource. The browser's helper and handoff screens
still need to consume these newly exposed operations.

## Live WebSocket and call-mode policy

Connect to `wss://<site>/v1/incidents/{id}/live` (or `ws://` on local HTTP).
The browser sends this JSON within five seconds of connection:

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
    "payload": {"type":"session.hello"}
  }
}
```

Only the primary incident actor/client may connect. `session.ready` always
returns authoritative `interactionMode`, `stateRevision`, `modeRevision`,
`authorityEpoch`, `voiceAllowed:false`, and `resumeRequired:true`, including
after reconnect. The client must reconcile its REST outbox and keep the local
audio/microphone gate closed until the user explicitly resumes. `mode.silence`
may be sent immediately, even ahead of the REST mode revision; it closes the
provider and returns `mode.silenced`. `resume.request` requires committed
`voice_guidance` and exact state/mode/authority revisions. `media.frame`
requires accepted resume, increasing sequence, matching `modeRevision`,
base64 data, and `contentType:"audio/pcm;rate=16000"` (at most 65,536 decoded
bytes). `image/jpeg` is reserved in the schema but returns `unavailable`.
Server replies include `resume.accepted`, `media.ack`,
`observation.proposed`, or `{"type":"error","code":"..."}`. Only unconfirmed
model observations are emitted; no Agent speech or clinical step is streamed.
Each proposal carries a stable `messageId` matching its `observationId`, the
current state/mode revisions, and an allowlisted `responsive` or
`breathing_normal` value. The browser must ask the user to confirm yes, no, or
unknown. A confirmed answer is saved through the REST snapshot path as a
`user_report` / `confirmed` observation before `/rule-evaluations` is called;
the model proposal never confirms itself.
Without `GEMINI_MODEL` and backend credentials, `resume.request` returns
`unavailable`; no external Gemini call is required for the structured REST
routes. The browser must discard stale output by mode revision even if the
server also rejects it.

## Error and availability contract

REST errors have one shape:

```json
{"error":{"code":"stale_revision","message":"Revision is stale","requestId":"<uuid>","details":{"stateRevision":2}}}
```

| HTTP result | Meaning for callers |
| --- | --- |
| `400` or `413` `invalid_input` | Body, enum, UUID, media size, or query parameter is invalid. |
| `401` `unauthorized` | Bearer token is missing, invalid, or expired. Create a new session; it will not inherit incident ownership. |
| `403` `unauthorized` / `expired` | Actor lacks incident scope, grant expired, or incident is closed/expired. Do not show cached private data as current. |
| `409` `stale_revision` / `invalid_input` | Refresh the authoritative revision or resolve an idempotency-key conflict; do not retry changed content under the same key. |
| `503` `unavailable` | Database or provider operation is unavailable. Retain the local outbox and current mode; do not invent AEDs, routes, or addresses. |

The active service stores normalized incident, event, snapshot, invitation,
grant, AED, and idempotency records in PostgreSQL. Event append and snapshot
projection commit in one `PostgresUnitOfWork`; a failure rolls both back. Compose
runs migrations before the API and retention cleanup hourly. Access expiry is
checked immediately even between cleanup runs. The legacy JSONB adapter remains
selectable with `INCIDENT_BACKEND=legacy`; existing JSONB incidents are not
automatically moved to normalized tables. Imported official AED records are
optional and never fabricated. When no walking-route provider is configured,
assignment estimates declare `routeBased:false` and straight-line uncertainty;
they must not be shown as walking directions or ETA. Clinical review, geocoding,
Google Maps UI, clinical review, and complete offline feature wiring remain
outstanding. The TypeScript interpreter exists and passes shared fixtures.
Tests use synthetic incidents and never dial 119.

## Workstream handoff

- **Rescuer UI (2):** The 119 entry renders before background session/incident
  bootstrap. Mode and quick-action reports use the shared runtime.
- **Browser runtime (3):** `web/src/lib/connection/` owns REST/WebSocket transport,
  error mapping, deduplication, and reconnect; `web/src/lib/offline/` owns the
  IndexedDB outbox and approved-shell cache; `web/src/lib/media/` owns immediate
  local silence and PCM microphone capture. `web/src/lib/rules/` now implements
  the shared schema and fixtures, including `unknown`, mode interrupts, stale
  revisions, and timers; keep Python/TypeScript cases aligned as rules change.
- **Helpers and handoff (4):** Create an independent actor per participant;
  redeem once, enforce scope/expiry in the UI, and read the same snapshot.
  The runner cannot read clinical data; EMS can read sanitized timeline pages.
  Render the new AED assignment and unavailable-report responses with route
  source/freshness, and show the canonical snapshot above MIST and the timeline.
- **Agent and API (1):** Flask now composes the normalized Workstream 5
  services. Keep Pydantic, checked OpenAPI, and shared browser transport types
  aligned when changing a field. The Live socket remains only for media and
  controls; structured operations use REST.
- **Rules/data services (5):** The domain services, normalized repositories,
  migration / cleanup commands, source adapter, and shared rule fixtures are
  implemented. Remaining changes in these paths should be contract fixes found
  during Workstreams 1 and 3 integration or clinically reviewed content updates.
