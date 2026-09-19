# Integration contract for workstreams 2–5

This document describes the Workstream 1 implementation that other workstreams
can call today. The checked HTTP source is [openapi.json](openapi.json), generated
from [Pydantic schemas](app/schemas/contracts.py). The Live protocol is defined
in [the gateway](app/api/live.py) and summarized here. The broader product rules
remain in [the SDD](../docs/sdd.md). Keep browser transport types together in
`web/src/types/` when that application is created.

## Current integration status

| Area | Available now | Work still needed |
| --- | --- | --- |
| REST boundary | Flask routes, Firebase ID token verification, Pydantic validation, JSON errors, OpenAPI | Workstream 5 persistent `IncidentService` and Firebase Rules |
| Live boundary | Authenticated WebSocket, control and PCM frame validation, silent reconnect, ADK observation adapter | Real credential-backed Live session test, reviewed guidance output and rule integration |
| Data | Explicit synthetic in-memory mock enabled only by `SYNTHETIC_MOCK_SERVICE=1` | Firestore events, projections, grants, AED and location services |

With no injected service and no mock flag, `/healthz` responds but structured
operations return `503 unavailable`. The mock's `customToken` is deliberately
invalid and its response has `mock: true`. Do not use mock responses as proof of
authentication, medical actions, dispatch, routing, or persistence.

## Shared rules for every consumer

- Use HTTPS REST JSON for structured operations. Use the WebSocket only for Live
  media and control. Firestore projections are scoped, read-only client views.
- Every REST route except `/healthz` requires
  `Authorization: Bearer <Firebase ID token>`. The invitee first obtains its own
  Firebase identity; `POST /v1/share-sessions` is also authenticated. A real
  service exchanges a valid invitation for a scoped Firebase custom token.
- The server derives the actor from the verified token. A URL `incidentId`,
  `helperId`, client-reported role, or QR contents never grants access by itself.
- UUID fields are strings in JSON. Timestamps use RFC 3339 with an offset
  (prefer UTC `Z`). Keep occurrence `clientTime` separate from server receipt.
- Preserve `incidentId`, `eventId`, `ruleVersion`, `stateRevision`,
  `modeRevision`, `snapshotRevision`, and `authorityEpoch`. Send stable UUIDs
  again when retrying an uncertain request; do not create a new action ID.
- `unknown` is distinct from `false`. A proposed observation is not a confirmed
  observation or a performed treatment. No API result proves a call connected.
- Responses set `Cache-Control: no-store`. Browser or service-worker caches must
  not retain private responses.

## Workstream 2: rescuer and call-mode UI

The first 119 control is a local browser action and must remain available before
network, authentication, GPS, or model startup. On dial-link activation, mute
locally first, send WebSocket `mode.silence` if connected, then queue or upload a
`mode.changed` event. This is a user/browser report, never telephone telemetry.

The accepted modes are `call_119`, `on_call`, `voice_guidance`, and `handover`.
Mode is separate from incident status (`active`, `handed_over`, `closed`) and
clinical state. The current synthetic service permits these reported changes:

| Current mode | Reason | Next mode |
| --- | --- | --- |
| `call_119` or `voice_guidance` | `dial_started` or `dispatcher_reported_active` | `on_call` |
| `call_119` | `user_reports_call_failed` | `voice_guidance` |
| `on_call` | `user_reports_call_ended_or_failed` | `voice_guidance` |
| `call_119`, `on_call`, or `voice_guidance` | `user_reports_ems_arrived` | `handover` |

A `mode.changed` event includes exactly
`{"interactionMode":"on_call","reason":"dial_started"}` in `detail`.
It carries the **next locally incremented** `modeRevision` and the current
expected `stateRevision`. Other event types carry the current committed
`modeRevision`. The browser's audio gate still rejects old output even if the
network or server is late. Voice does not restart on reconnect, page resume, or
visibility change; the user must explicitly request it after reporting that
dispatcher guidance is unavailable.

Quick buttons report actions through `action.reported` with `detail.action`.
They do not assert that an issued instruction was performed. The canonical
scene snapshot, not a separate model summary, supplies the reporting cheat
sheet. The UI should display provenance, uncertainty, and snapshot freshness.

## Workstream 3: shared browser transport, media, and offline sync

### Register and upload

1. Generate `incidentId`, `primaryClientId`, `clientInstanceId`, and stable
   `eventId` values locally. Preserve them across retry and reload.
2. After Firebase authentication, `POST /v1/incidents` with `incidentId`,
   `primaryClientId`, and `ruleVersion`. Repeating identical registration for
   the same owner is idempotent. Keep the returned revisions and authority
   epoch. A different owner or different registration fields conflict.
3. Upload 1–50 ordered events through
   `POST /v1/incidents/{incidentId}/event-batches`. Each event has `eventId`,
   `type`, `detail`, `clientId`, `clientInstanceId`, increasing
   `clientSequence`, `clientTime`, `authorityEpoch`, `stateRevision`,
   `modeRevision`, and `ruleVersion`. The current mock accepts increasing
   sequences per `(clientId, clientInstanceId)` and checks each event against
   the current revisions. Preserve local occurrence order and clock uncertainty
   in the real offline store.
4. Inspect **every** `acknowledgements` entry, even on HTTP 200: `accepted`,
   `duplicate`, or `conflict` with a `code`. Only accepted or identical
   duplicates may leave the outbox. An altered duplicate ID conflicts. Use the
   returned revisions to reconcile; never turn a stale conflict into a blind
   last-write-wins update. Treat `lastAcknowledgedClientSequence` as advisory
   when multiple client instances exist; per-event acknowledgements are the
   source of truth.

Example synthetic dial report (the first committed event after registration):

```json
{
  "events": [{
    "eventId": "44444444-4444-4444-8444-444444444444",
    "type": "mode.changed",
    "detail": {"interactionMode": "on_call", "reason": "dial_started"},
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

The client-uploadable event types are `mode.changed`, `call.reported`,
`action.reported`, `event.corrected`, `observation.proposed`,
`observation.confirmed`, `command.acknowledged`, `timer.elapsed`, and
`helper.updated`. Server-only decisions and snapshot commits are not accepted
as client event types. `call.reported` requires `source: "user"` and a
`reportedState` of `attempted`, `active`, `ended`, `failed`, or `uncertain`.
Corrections reference `correctsEventId`; they do not overwrite an event.
See `EventInput.validate_detail` for the current detail allowlist.

### Live WebSocket v1

Connect from an origin listed in `ALLOWED_ORIGINS` to
`/v1/incidents/{incidentId}/live`. The first JSON message is an auth wrapper:

```json
{
  "type": "auth",
  "token": "<Firebase ID token>",
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
    "payload": {"type": "session.hello", "lastAcknowledgedClientSequence": 1}
  }
}
```

The server verifies the token, primary ownership, client ID, incident ID, and
authority epoch before accepting media. `session.ready` returns authoritative
`interactionMode`, `stateRevision`, `modeRevision`, `authorityEpoch`,
`voiceAllowed:false`, and `resumeRequired:true` on **every connection**. It
does not certify the client-supplied event boundary. Reconcile the REST outbox
first; reconnection never resumes capture or playback automatically.

After auth, every client control is a `LiveEnvelope` with the same top-level
fields and an increasing `clientSequence`:

| `payload.type` | Payload fields | Behavior |
| --- | --- | --- |
| `mode.silence` | `type` | Closes the provider and clears pending output immediately, even if the local `modeRevision` is ahead of REST. Returns `mode.silenced`. |
| `resume.request` | `type` | Requires current committed `voice_guidance`, exact `stateRevision`, `modeRevision`, and `authorityEpoch`, plus an explicit user action. Returns `resume.accepted` or an error. |
| `media.frame` | `type`, `frame` | Requires accepted resume. `frame` has `sessionId`, increasing `sequence`, matching `modeRevision`, `contentType`, and base64 `data`. Returns `media.ack`. |

Accepted audio is `audio/pcm;rate=16000`, at most 65,536 decoded bytes per
frame. `image/jpeg` is reserved in the schema but currently returns
`unavailable`; do not rely on camera Live capture. Server-side model output is
only `observation.proposed` with the current mode revision. The browser must
discard stale output and must not present proposals as confirmed facts or
treatment. No Agent speech is implemented yet.

### Error handling

REST errors use `{"error":{"code":"...","message":"...","requestId":"...","details":{...}}}`.
Common codes: `invalid_input` (400 or 413), `unauthorized` (401/403),
`expired` (403), `stale_revision` (409), `rule_mismatch` (per-event conflict),
and `unavailable` (503). A malformed or oversized request is rejected before
service work. Live errors use `{"type":"error","code":"..."}`; media and
control acknowledgements are separate from REST event persistence.

## Workstream 4: helpers and EMS handoff

The primary creates invitations with
`POST /v1/incidents/{incidentId}/shares`. Supply `scope` as `aed_runner`,
`ambulance_greeter`, or `ems_viewer`, `expiresInSeconds` from 60 to 3600, and
an `idempotencyKey` UUID. Runner and greeter invites require `helperId`; EMS
invites must omit it. Keep the returned secret out of ordinary logs. An
invitee calls `POST /v1/share-sessions` with its own Firebase ID token and
`{"secret":"..."}`. The real service must check expiry, one-time redemption,
revocation, and scope before issuing a usable custom token.

Helpers report their own task or location through
`POST /v1/incidents/{incidentId}/helpers/{helperId}/updates`. Supply stable
`updateId`, `expectedAssignmentRevision`, `reportedAt`, and either a `status`
(`accepted`, `en_route`, `arrived`, `obtained`, `unavailable`) or both `lat` and
`lng`. Optional `locationAccuracyMeters` is nonnegative. A runner may read
`GET /v1/incidents/{incidentId}/aeds?limit=10`; results distinguish
`straightLineMeters` from optional walking distance and ETA. `availability`
can be `unknown`, and `dataUpdatedAt` or `routeUpdatedAt` may be `null`.

An EMS viewer may read
`GET /v1/incidents/{incidentId}/handoff/events?limit=25&cursor=...`.
The response includes `snapshotRevision`, `generatedThroughRevision`, a
filtered event page, and optional `nextCursor`. A runner cannot read this
timeline; a greeter cannot read the full timeline. The handoff UI must show
the canonical scene snapshot **above** MIST and the timeline. There is no
REST `GET snapshot` route in this package; Workstream 5 supplies the scoped
Firestore snapshot projection described in the SDD. Do not build a separate
helper or EMS model summary.

## Workstream 5: persistent service implementation

Implement [IncidentService](app/services/ports.py) and inject it into
`create_app(service=...)`. The current `app/wsgi.py` creates the app without a
real service; do not deploy it as a functional production backend yet. Replace
the synthetic mock with transactional event storage, pinned rules, canonical
snapshot projection, scoped grants, invitation hashing and expiry, AED search,
route freshness, and sanitized timeline pages. Preserve the HTTP models and
error codes unless a coordinated additive contract update is made.

The tool facade in `app/tools/adapters.py` creates no authority of its own:
it validates a server-created `ToolContext` with actor UID, incident ID,
expected state/mode revisions, and authority epoch before delegating.
`get_next_step`, helper dispatch/status, and image analysis currently fail
closed with `unavailable`. Model proposals cannot commit decisions, dispatch
helpers, or mark treatment completed. Workstream 5 should supply reviewed rule
decisions and durable idempotency before those operations are enabled.

## Contract checks

From `agent/` with Python 3.12 and the `test` dependencies installed:

```sh
PYTHONPATH=. .venv/bin/python scripts/generate_openapi.py --check
PYTHONPATH=. .venv/bin/pytest -q
```

Update Pydantic schemas, generated OpenAPI, route/service implementation,
consumer types, and affected tests together when a field or error changes.
