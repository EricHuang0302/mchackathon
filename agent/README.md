# Agent API implementation

This package is the Workstream 1 Flask boundary. The HTTP contract is generated
from Pydantic models in `app/schemas/contracts.py` into `openapi.json`. The
WebSocket contract is described below because OpenAPI describes HTTP routes.

## Local run and checks

Use Python 3.12. From `agent/`:

```sh
python -m venv .venv
.venv/bin/pip install -e '.[test,live]'
PYTHONPATH=. .venv/bin/python scripts/generate_openapi.py --check
PYTHONPATH=. .venv/bin/pytest -q
```

Set `ALLOWED_ORIGINS=https://your-frontend.example` to allow browser requests.
`SYNTHETIC_MOCK_SERVICE=1` enables a volatile synthetic service for local API
contract demonstrations. It is **not** a database, does not use Firebase grants,
and never returns real geocoding, AED routes, or clinical decisions. Without a
Workstream 5 `IncidentService`, structured operations return `503 unavailable`.
`GEMINI_MODEL` enables the ADK Live observation adapter when the `live` extra and
server-side Gemini credentials are available. Keep these credentials out of
`VITE_*`. No model response is forwarded as clinical speech or a decision.

```sh
ALLOWED_ORIGINS=http://localhost:5173 SYNTHETIC_MOCK_SERVICE=1 \
  .venv/bin/gunicorn --bind 127.0.0.1:8080 --workers 1 --threads 32 --timeout 0 app.wsgi:app
```

The Dockerfile uses the same Gunicorn command for Cloud Run. Configure the
Cloud Run service with the permitted frontend origin, a service account able to
verify Firebase ID tokens, and server-side Gemini credentials if Live analysis
is enabled. Cloud Run WebSocket connections are time-limited; the client must
reconnect and synchronize REST events before requesting an explicit resume.
Each WebSocket occupies a Gunicorn thread; size Cloud Run concurrency and
instance count accordingly.

## HTTP contract and service boundary

All endpoints except `/healthz` require `Authorization: Bearer <Firebase ID
token>`. The server derives the actor from the verified token. The service
checks incident ownership or a scoped, unexpired grant; a known incident ID is
not permission. Every response has `Cache-Control: no-store`. Errors use
`{"error":{"code":"stale_revision","message":"...","requestId":"...","details":{...}}}`.

| Consumer | Endpoint | Service method |
| --- | --- | --- |
| Primary, browser sync | `POST /v1/incidents` | `create_incident` |
| Primary, browser sync | `POST /v1/incidents/{id}/event-batches` | `upload_events` |
| Primary, snapshot | `POST /v1/incidents/{id}/scene-observations` | `add_observations` |
| Primary, location | `POST /v1/incidents/{id}/location-descriptions` | `describe_location` |
| Primary, helper and EMS invite | `POST /v1/incidents/{id}/shares` | `create_share` |
| Invitee | `POST /v1/share-sessions` | `exchange_share` |
| Own helper task | `POST /v1/incidents/{id}/helpers/{helperId}/updates` | `update_helper` |
| Primary or runner | `GET /v1/incidents/{id}/aeds` | `list_aeds` |
| Primary or EMS | `GET /v1/incidents/{id}/handoff/events` | `handoff_events` |
| Primary | `PATCH /v1/incidents/{id}` | `patch_incident` |

The `IncidentService` protocol in `app/services/ports.py` is the Workstream 5
integration point. It must implement transactional revision checks, stable
event IDs, append-only corrections, idempotent mutations, grant expiry,
snapshot projection, sanitized handoff fields, AED search, and retained rule
versions. The synthetic mock demonstrates HTTP behavior only. Real share
exchange must issue a Firebase custom token after persisting the grant; the
mock's `MOCK_ONLY_NOT_A_FIREBASE_TOKEN` value must never be used by a client.

For Workstream 3, an event batch contains bounded ordered events with
`eventId`, `clientId`, `clientInstanceId`, `clientSequence`, `clientTime`,
`authorityEpoch`, `stateRevision`, `modeRevision`, and `ruleVersion`. A
`mode.changed` event carries the next locally incremented `modeRevision`;
other events carry the current committed revision. A duplicate
ID with identical content returns `duplicate`; an altered duplicate or stale
revision returns a per-event `conflict`. For Workstream 2, `mode.changed` is an
explicit browser report with `interactionMode` and `reason`; no telephone state
is inferred. For Workstream 4, runner grants cannot read the handoff timeline;
EMS grants are read-only; helper updates require the matching helper ID and
assignment revision. Unknown or expired grants deny access.

Example event body:

```json
{"events":[{"eventId":"4b7a9f79-b3b4-4a60-91cb-b958d570f3ef","type":"action.reported","detail":{"action":"cpr_started"},"clientId":"9200c811-3521-4a66-a037-9bd0bb4dc698","clientInstanceId":"2bc8a203-21cc-4d95-9a0a-ef22ee924679","clientSequence":7,"clientTime":"2026-09-19T00:00:00Z","authorityEpoch":1,"stateRevision":3,"modeRevision":2,"ruleVersion":"demo-v1"}]}
```

## Live WebSocket v1

Connect to `WS /v1/incidents/{id}/live` from an allowlisted Origin. The first
JSON message is `{"type":"auth","token":"<Firebase ID token>","envelope":
<LiveEnvelope>}`. The envelope payload is
`{"type":"session.hello","lastAcknowledgedClientSequence":7}`. Authentication
and incident scope are checked before any media is accepted. The response is
`session.ready` with current revisions and `voiceAllowed:false` on **every**
connection or reconnect. It also returns `resumeRequired:true`; the client must
reconcile pending REST events before a user explicitly requests resume. The
server does not echo a client supplied acknowledgement as an authoritative
boundary.

Subsequent messages use the `LiveEnvelope` schema with `protocolVersion:1`,
`messageId`, `incidentId`, `clientId`, `clientInstanceId`, `clientSequence`,
`clientTime`, `authorityEpoch`, `stateRevision`, `modeRevision`, and `payload`.
The client can send `mode.silence` immediately, including while its local mode
revision is ahead of the server; the server closes the provider and flushes
pending proposals. `resume.request` is accepted only after REST has committed
`voice_guidance` and the user explicitly resumes. `media.frame` carries a
`frame` with `sessionId`, increasing `sequence`, `modeRevision`,
`contentType:"audio/pcm;rate=16000"`, and base64 `data` (at most 64 KiB decoded).
Camera frames are reserved by the contract and currently return `unavailable`.
The server emits `media.ack`, `observation.proposed` or `error`, all tied to
the current mode revision. It never streams unreviewed model speech. Local
browser audio and microphone gates still decide whether a frame can play or
upload. ADK sessions are volatile; structured event state remains in the
Workstream 5 service and must be reconciled after reconnect.

The ADK adapter uses Google's `InMemoryRunner.run_live` and a fresh
`LiveRequestQueue` for each permitted session. It accepts only a short JSON
allowlist of **unconfirmed** observation proposals. Invalid model output is
discarded. Approved guidance, rule decisions, and tool actions await the
Workstream 5 rule and persistence service. The tool facade in
`app/tools/adapters.py` validates server-created identity and revisions before
delegating; unavailable Workstream 5 operations fail closed.
