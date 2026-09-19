# First Aid Copilot — Software Design Document

Status: local deployment baseline with a partially implemented React / Vite frontend and Flask API. Sections describing clinical rules, AED dispatch/reassignment, offline PWA behavior, and full handoff are target design unless explicitly marked implemented. For callable backend behavior, use [the integration guide](../agent/INTEGRATION.md) and checked [OpenAPI](../agent/openapi.json).

Product name: 急救副駕 (First Aid Copilot). Primary interface language: Traditional Chinese (`zh-TW`). Operating context: Taiwan and emergency number 119. Repository collaboration rules are in [AGENTS.md](../AGENTS.md).

> This is an emergency assistance prototype. Its medical decision-making has not been clinically validated. Direct users to contact 119 first and follow the dispatcher's instructions whenever dispatcher guidance is available.

## 1. Product Definition and Scope

**The dispatcher leads; the Agent assists.** The product supports reporting, scene records, AED retrieval, and handoff. During dispatcher guidance, it stays silent and presents a reporting cheat sheet, quick-event buttons, a scene snapshot, and helper progress. When a user reports that dispatcher guidance ended or a call could not connect, rule-based voice guidance becomes available.

All participant interfaces are planned in one React browser application; there is no native mobile app. The current frontend has synthetic demo flows, and installable/offline PWA behavior is not implemented yet. PWA installation will be optional. The prototype handles one patient per incident and one primary rescuer browser session, with additional helper and read-only handoff sessions. Patient populations, exclusions, and clinical eligibility must be declared in the reviewed rule package.

| ID | Capability | Required behavior |
| --- | --- | --- |
| F01 | Dial-first entry | The first screen provides a large 119 link, a one-line scene-safety reminder, speakerphone instructions, and a suggestion to designate another caller. No assessment, permission, registration, or model initialization blocks the link. |
| F02 | Conditional voice | Online speech interaction is enabled only in voice-guidance mode with explicit user activation. Buttons remain available throughout the flow. |
| F03 | Reviewed guidance | Support assessment, CPR, bleeding-control, and recovery-position flows defined by reviewed rules and fixed instruction templates. |
| F04 | Foreground timing | Provide a local visual CPR beat, optional audio outside call mode, and applicable two-minute reminders without relying on model timing. |
| F05 | Optional scene capture | Selected camera frames can propose snapshot fields, with user confirmation and visible uncertainty. Camera access is optional. |
| F06 | Helper coordination | QR links open an AED-runner or ambulance-greeter task without installation. The greeter can read the same scene snapshot as EMS. |
| F07 | AED retrieval | Search candidates, show walking routes, track foreground helper updates and estimated return time, and reassign an unavailable AED. |
| F08 | Event history | Record user reports, rule decisions, command results, helper updates, corrections, and timestamps as distinct events. |
| F09 | Handoff | Display the scene snapshot first, then MIST and the complete timeline. The primary session can show its local record when the hosted viewer cannot connect. |
| F10 | Lightweight offline operation | After required resources have been cached, retain approved text, button-driven TypeScript rules, a local snapshot, an event outbox, and cached government AED records. |
| F11 | Recovery and synchronization | Restore available local records and reconcile reconnects without duplicate actions, stale speech, or reverting the current interaction mode. |
| F12 | Scoped temporary access | Restrict participant access by incident and task, expire sharing grants, and apply data retention to server and local records. |
| F13 | Manual call mode | Clicking the call link or reporting an external call immediately mutes the Agent. Users explicitly report call end or failure before voice can resume. |
| F14 | Reporting cheat sheet | Present location, circumstances, patient condition, and performed actions in large readable text, preserving unknown values. |
| F15 | Shared scene snapshot | Maintain location / access details, circumstances, patient condition, performed actions, people present, and hazards with provenance and freshness. |
| F16 | Quick-event controls | Persist one-tap reports such as `CPR started`, `Someone is fetching an AED`, and `EMS arrived`, with correction support. |

The core demonstration is silent call support, inaccessible-AED reassignment, and snapshot-first handoff, with voice and offline variants. Automatic telephone-state detection, automatic speakerphone control, guaranteed background execution, downloaded language models, diagnosis, medication recommendations, automated dispatch, and multi-patient triage are outside scope.

## 2. System Architecture

```mermaid
flowchart LR
    Browser[One React PWA: rescuer, helper, EMS] -->|same-origin HTTP and Live WebSocket| Nginx[User-managed Nginx reverse proxy and static files]
    Nginx --> API[Flask API / Live gateway]
    API --> DB[(Local PostgreSQL volume)]
    API --> Gemini[External Gemini Live, optional]
    API --> MapsAPI[External Google Maps APIs, optional]
    Browser --> MapsUI[External Google Maps JS, optional]
    Browser --> Local[(IndexedDB / service worker, planned)]
```


The baseline media path is browser → Flask Live WebSocket gateway → ADK → Gemini Live API. Structured application operations use RESTful JSON over HTTPS. Long-lived credentials stay on the backend. PostgreSQL carries structured state, not raw Live media. The user-managed Nginx is the browser entry point; it runs outside this repository’s Compose stack. The backend is one application with internal modules; Redis is not required for the current prototype.

The current Live gateway accepts authenticated PCM audio and can emit unconfirmed observation proposals; it does not stream speech or clinical instructions. Optional external model operations use Google Gemini. Optional image extraction can run separately from the Live voice session, allowing structured call-mode work to continue with no microphone upload or spoken response. Model IDs are configuration and must be verified against the selected session's language, modality, and tool requirements. [Gemini Live API](https://ai.google.dev/gemini-api/docs/live-api)

| Component | Authority |
| --- | --- |
| React feature routes | Present information, collect explicit user reports, and request authorized operations. |
| Browser mode controller | Select the interaction mode from UI events and enforce the local audio / microphone gate immediately. |
| Browser runtime | Execute permitted commands, schedule foreground output, persist local records, and evaluate rules offline. |
| Gemini | Propose structured observations and bounded conversational responses. It cannot select clinical transitions or authorize treatment. |
| Rule interpreters | Produce deterministic state transitions, template references, action intents, and timer changes. |
| Backend services | Enforce identity and revisions, persist events, project snapshots, and coordinate helpers and AED retrieval. |

Only the primary session executes guidance. Online decisions are committed by the backend; offline decisions use the same pinned rule package in TypeScript. The browser's current mode and playback gate are always checked before any output, regardless of server state.

## 3. Technology and Frameworks

| Layer | Selected technology | Purpose |
| --- | --- | --- |
| All participant interfaces | React, TypeScript, Vite, React Router | One mobile-first application, shared types / components, and separate participant routes. |
| Browser media | `getUserMedia`, Web Audio API, AudioWorklet where needed | Permission-based microphone / camera access and local playback / audio processing. |
| Browser interaction state | Shared TypeScript controller exposed through React context / hooks | Mode changes, audio gating, clinical-state presentation, and explicit user controls. |
| Local persistence | IndexedDB behind a shared repository | Incident state, event outbox, command results, rule metadata, and AED records. |
| PWA assets | Web app manifest, service worker, Cache Storage | Optional installation and caching of the application shell and approved public assets. |
| Browser transport | `fetch`, WebSocket | RESTful JSON mutations, Live media / control transport, and scoped snapshot reads. |
| Backend | Python 3.12, Flask, Pydantic, Google ADK, Google Gen AI SDK | RESTful API validation, Live sessions, tool orchestration, and application services. |
| Rules | Restricted YAML, JSON Schema, Python and TypeScript interpreters | Shared definitions and deterministic online / offline behavior. |
| Mapping and location | Geolocation API, Maps JavaScript API, Routes API, Geocoding API | Foreground location reports, map display, walking estimates, and candidate addresses. |
| Data and identity | PostgreSQL, opaque local sessions | Incident storage, scoped sessions, access grants, and projection updates. |
| Deployment | Docker Compose, user-managed Nginx, Docker volumes | API and database containers; external reverse proxy and frontend static files. |
| AED ingestion | Python ETL | Normalize and version the selected government dataset. |
| Verification | Vitest, Playwright, pytest, local PostgreSQL integration tests | Browser behavior, rule parity, service contracts, access rules, and scenarios. |

There is one frontend manifest, lockfile, and router. Feature components use shared media, transport, and storage adapters. Do not create separate applications for the rescuer and helpers. Exact dependencies and versions will be pinned in the implementation manifests.

The supported demonstration uses tested mobile-browser profiles over HTTPS with the relevant pages visible. Record the browser / device versions used in verification; installation alone does not expand browser capabilities. [PWA overview](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps)

## 4. Routes and User Experience

Sections 4–8 specify target product behavior unless a current implementation is explicitly identified. Today the frontend routes are synthetic demo screens; they do not call the Flask API.

### 4.1 Rescuer Routes

The current `/` route is a demo entry screen, and `/incidents/:incidentId` is a planned active-incident route. The target UI first shows a large `tel:119` link, one-line scene-safety reminder, speakerphone instructions, and a suggestion to designate another caller. Dial access does not wait for persistent storage, authentication, GPS, or a model session.

Before handing control to the telephone link, the browser synchronously closes its audio gate and queues a `dial_started` event. The system decides how a telephone link is handled; record only the attempted launch, not a successful connection or enabled speakerphone. The caller enables speakerphone in the system interface and returns to the PWA for the cheat sheet when practical. [Telephone links](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/a#linking_to_telephone_numbers)

Call mode presents the cheat sheet, quick buttons, helper progress, and a visual beat when applicable. Voice-guidance mode presents one approved instruction with large `Yes`, `No`, `Unsure`, repeat, correction, and stop-speaking controls. Manual controls report `Dispatcher is on the line`, `Someone else is calling`, `Call ended`, and `Could not connect`. The interface does not imply it can observe the real telephone call.

### 4.2 Reporting Cheat Sheet and Scene Snapshot

The cheat sheet is a large-type view of the shared scene snapshot. Its order is location, circumstances, patient condition, and performed actions, followed by people present and hazards. Wording and ordering require review by dispatch or rescue professionals.

| Field | Content |
| --- | --- |
| Location | Coordinates, accuracy, address, landmark, floor, entrance, access notes, and capture time. |
| Circumstances | What happened and the reported occurrence time; unknown if not witnessed. |
| Patient condition | Structured observations with source, confirmation / uncertainty labels, and last-observed time. |
| Performed actions | Reported actions and their times, kept separate from recommendations and issued commands. |
| People present | Reported patient and bystander counts plus helper-task summaries; additional patients are outside the single-patient flow. |
| Hazards | Reported or camera-proposed hazards, with an empty field treated as unknown. |

In the target scene projection, each field retains its value, source, confirmation state, observation time, and evidence references. Reverse geocoding proposes an address; users confirm or enter landmarks, floor, and access information. Model or camera output cannot silently replace a confirmed fact. The planned deterministic projector produces `snapshotRevision`, `updatedAt`, and the source-event boundary; today `GET snapshot` returns only typed observations and revisions. [Google reverse geocoding](https://developers.google.com/maps/documentation/geocoding/guides-v3/requests-reverse-geocoding)

Quick buttons persist reports before upload and update the local projection immediately. A reported AED runner departure does not prove a QR task was accepted. Corrections append a reference to the original event and distinguish entry time from any user-entered occurrence time. Failed local persistence must be visible rather than acknowledged as a saved record.

### 4.3 Helper and Handoff Routes

The current `/join/:inviteId` route is a demo screen and does not exchange an invitation. The target flow exchanges a QR invitation for an authenticated grant, then opens `/incidents/:incidentId/helpers/:helperId` or `/incidents/:incidentId/handoff`. The invitation secret travels in the URL fragment, is sent to the exchange endpoint, and is removed from browser history before third-party map resources load. It contains no clinical data.

An AED runner sees its task, destination, access notes, map / walking route, and return location. It can report arrival, inability to obtain the AED, collection, and delivery. Location permission is requested only for the task; manual status reporting works without it. Tracking is expected only while the helper page is visible, and stale updates are explicitly labeled.

The ambulance greeter sees its meeting task and the same scene-snapshot document as EMS. The handoff page shows that snapshot first, then MIST and a paginated full timeline. MIST represents mechanism / medical complaint, injuries, signs, and treatment. Unknown fields remain unknown, and a recommended action is never displayed as completed treatment.

A hosted QR viewer requires connectivity and a valid grant. Offline handoff uses the primary session's locally stored view shown directly on screen. Scanning or viewing a QR code does not mark the incident handed over.

## 5. Interaction Modes and Output Policy

```mermaid
stateDiagram-v2
    [*] --> call_119
    call_119 --> on_call: dial_started or dispatcher_reported_active
    call_119 --> voice_guidance: user_reports_call_failed
    on_call --> voice_guidance: user_reports_call_ended_or_failed
    voice_guidance --> on_call: dial_started or dispatcher_reported_active
    call_119 --> handover: user_reports_ems_arrived
    on_call --> handover: user_reports_ems_arrived
    voice_guidance --> handover: user_reports_ems_arrived
```

The backend currently validates these mode transitions; browser mode controls and its local audio gate are not connected yet. Transitions into `voice_guidance` require the user to report that no dispatcher remains guiding the scene, including calls on another person's phone. A local idle browser, a visible tab, microphone silence, or a network timeout cannot establish that condition.

| Mode | Permitted behavior |
| --- | --- |
| `call_119` | Silent entry screen, emergency access, and local incident preparation without a blocking questionnaire. |
| `on_call` | No Agent speech, microphone upload, spoken reminders, or metronome sound. Quick records, snapshots, helper coordination, and foreground visual timing remain available. |
| `voice_guidance` | Approved spoken / text guidance, permitted online voice interaction, optional audible metronome, and rule-defined reassessment. |
| `handover` | Silent snapshot-first record and QR display. Guidance does not restart when call or connection events arrive. |

`interactionMode`, `clinicalState`, `connectionMode` (`online`, `offline`, `resyncing`), `guidancePaused`, and incident `status` (`active`, `handed_over`, `closed`) are separate fields. Mode changes retain treatment history and elapsed time; stale clinical observations require the rule-defined clarification or reassessment.

Each mode or pause-policy change increments `modeRevision` locally before server synchronization and invalidates queued output from the previous revision. Entering call mode cancels current playback, flushes queued speech, stops Agent microphone capture, and disables audio timing. Delayed frames and commands from another mode revision are discarded. Reconnection never overrides the local mode.

When the page becomes hidden, set `guidancePaused`, stop media capture and playback, persist available state, and mark visual timing / local tracking suspended. Visibility changes do not change reported call status. On return, refresh data, display any interruption, and require an explicit user action before restarting voice. Browsers may suspend animations and throttle background timers. [Page visibility and background limits](https://developer.mozilla.org/en-US/docs/Web/API/Page_Visibility_API)

Backend helper services can process reports from other connected participants while the primary tab is suspended. The primary UI catches up when resumed; it must not claim its own browser continued running throughout the interruption.

## 6. Shared Rules and Model Boundaries

### 6.1 Rule Package

The planned `rules/` package will contain schemas, flows, approved instruction templates, and shared fixtures; that directory and both interpreters are not present yet. A package includes `schemaVersion`, `ruleVersion`, content hash, supported populations, clinical references, review status, and compatible interpreter versions. Each incident pins one version, which remains available for its active online and offline sessions.

The rule language supports named states, required observations, ordered transitions, explicit unmatched-input behavior, allowlisted actions, template parameters, timer lifecycle events, and interaction-mode interrupts. Conditions are limited to declared comparisons and `all`, `any`, and `not`. Missing observations become `unknown`, never `false`.

Python and TypeScript use the same normalization and evaluation order. Loaders reject duplicate YAML keys, implicit type ambiguities, unsupported operators, dangling transitions, missing templates, and arbitrary executable expressions. Shared fixtures verify identical state, instruction, action, and timer results in both runtimes.

Clinical families include assessment, CPR, bleeding control, recovery-position guidance, AED support, and reassessment. The requested CPR reminder interval is 120 seconds where the reviewed flow enables it. Eligibility, wording, exception handling, and uncertainty rules belong to the reviewed package; a reminder never automatically stops treatment or invents a new clinical decision.

### 6.2 Observation and Decision Contracts

An observation includes `observationId`, allowlisted `key`, typed `value`, `source`, `observedAt`, `receivedAt`, `confirmation`, and `evidenceEventIds`. Boolean observations use `true`, `false`, or `"unknown"`. Sources distinguish voice reports, buttons, camera proposals, and other explicitly supported inputs. A model proposal cannot confirm itself, and a camera frame alone cannot establish a safe scene or normal breathing.

A `Decision` includes the pinned rule version, accepted observation IDs, source / target clinical state, `reasonCode`, optional approved template ID and parameters, allowed action intents, timer changes, and expected state / mode revisions. Interpreters are pure evaluators; adapters perform external actions only after authorization and revision checks.

The backend commits online decisions before issuing commands. Offline decisions and resulting reports are recorded locally. Commands have stable IDs, an authority epoch, state / mode revisions, and expiry. The client records `received`, `started`, `completed`, `failed`, or `interrupted` results. Idempotent desired-state operations prevent duplicate metronome starts; an uncertain external outcome is reconciled rather than blindly repeated.

Critical instructions are fixed reviewed text, spoken through packaged recordings or an available browser speech voice. Online conversational audio may clarify input or report coordination status only when the local gate permits it. It must not carry unconstrained treatment advice; clinical follow-up answers resolve to approved templates. A model prompt alone is not the enforcement boundary.

## 7. Browser Media, Timing, and Offline Runtime

### 7.1 Media and Foreground Timing

Microphone and camera access use `getUserMedia` over HTTPS with permission. Audio adapters convert captured samples to the selected Live session format; do not assume compressed `MediaRecorder` output can be forwarded as raw PCM. Camera frames are optional, explicitly enabled, rate-limited, and dropped when stale. Calls are not recorded or transcribed by the Agent. [Browser media capture](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)

Create or resume Web Audio playback from a user gesture and provide a visible enable-audio control when playback is blocked. The shared audio controller owns model playback, template speech, and metronome output, and cancels all of them when mode or pause state prohibits audio. Missing speech voices fall back to approved text or already cached recordings. [Web Audio practices](https://developer.mozilla.org/en-US/docs/Web/API/Web_Audio_API/Best_practices)

The metronome is generated in the browser, never streamed from the model. Use the audio clock for permitted sound and elapsed-time-based scheduling for visual beats, rather than counting React renders. Store timer definitions and treatment start events; use a monotonic clock during an active page lifetime. Audio is muted in call mode. Timers due while hidden or muted do not produce a burst of reminders on return.

Reloads create a new page clock. Restore history, show the interruption, and reconcile time and current observations before resuming applicable reminders. System clock changes must be treated as uncertainty. An optional screen wake lock can reduce accidental screen sleep on supported visible pages, but can be denied or released and does not guarantee background execution. [Screen Wake Lock API](https://developer.mozilla.org/en-US/docs/Web/API/Screen_Wake_Lock_API)

### 7.2 PWA Cache and Local Storage

The planned service worker will cache the public app shell, versioned approved templates / recordings, the normalized rule bundle, and permitted government AED-cache assets. No service worker is present in the current frontend. The planned worker must not cache authenticated API responses, invitation secrets, clinical pages as HTML snapshots, raw media, or map tiles. Private records belong in the primary session's controlled IndexedDB store, not a shared HTTP cache.

Offline readiness requires a completed prior load of the necessary assets and rule version. A first-ever visit without connectivity cannot load an uncached website. Optional installation is not a prerequisite for use and is not proof that all offline resources are ready. Show explicit readiness and missing-resource states. [PWA offline operation](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Guides/Offline_and_background_operation)

The planned IndexedDB store contains:

- Local incident state, interaction mode, pinned rule metadata, and scene-snapshot projection.
- An ordered outbox of observations, quick records, mode changes, corrections, and command results.
- Command deduplication / acknowledgement records and timer restoration data.
- Versioned government AED records with source freshness and local expiry.

Write related state and outbox entries in a transaction before acknowledging a saved report. Quota or storage failures display a recording-degraded state; emergency access and available guidance remain usable. Browser storage can be cleared or evicted, so unsynchronized records must not be described as permanently retained. A persistence request may help where available, without guaranteeing recovery. [Browser storage limits](https://developer.mozilla.org/en-US/docs/Web/API/Storage_API/Storage_quotas_and_eviction_criteria)

Do not force a waiting service worker to replace an active incident's app / rule versions. Activate an update when no incident is active or after an explicit reload with safely stored state. A compatible existing rule bundle must remain available until its incidents finish.

### 7.3 Capability Degradation

| Unavailable capability | Behavior |
| --- | --- |
| Gemini / network voice | Use large buttons and the local rule interpreter with fixed text / cached prompts. No language-model download is required. |
| Microphone or camera | Continue manual observations and quick records without blocking the incident. |
| Speech output | Show the approved text and any available cached recording; obey the audio gate regardless of voice availability. |
| Server data or authentication | Keep local records and cached rules; show remote helper data as stale. New shared sessions require connectivity. |
| Routing / maps | Show cached AED addresses, access notes, age, and straight-line distance where coordinates are available. Do not fabricate walking directions or an ETA. |
| Local persistence | Clearly identify unsaved records and limited recovery. Do not block the telephone link waiting for a write. |
| Cached shell or rule bundle | Explain the missing offline capability; do not substitute generated clinical advice. |
| Visible page | Suspend browser media / visual timing and local tracking; reconcile on return without inferring that a telephone call ended. |

### 7.4 Synchronization and One Primary Session

Assign a random installation-scoped `clientId` in browser storage and a tab-scoped `clientInstanceId`; neither is a hardware identifier. Events have stable UUIDs, `clientSequence`, `clientTime`, rule version, mode revision, and authority epoch. The authenticated server assigns identity and receipt time and deduplicates by event ID.

Only one tab may execute guidance for an incident. On the supported browser profile, use an origin-scoped Web Lock for that incident; another tab displays a read-only / already-open state. Across browser profiles, backend ownership and revision checks reject a second primary writer. If reliable local arbitration is unavailable, do not claim safe multi-tab offline operation; limit that profile to an explicitly controlled single-session demo. [Web Locks API](https://developer.mozilla.org/en-US/docs/Web/API/Web_Locks_API)

The target offline runtime will preserve the current interaction mode, queue ordered events, and reconcile the outbox after reconnect. The current backend accepts bounded event batches with exact revision and authority-epoch checks; it does not merge a divergent offline branch or advance an authority epoch on its own. A conflict must remain visible to the client rather than being treated as a successful merge.

Historical replay updates records and projections without re-executing treatment prompts, completed commands, or helper dispatches. Conflicting ownership, unsupported rule versions, or an unreconcilable branch keep the client in local mode with a visible conflict. Server receipt time does not reorder offline occurrences, and the latest local call mode cannot be overwritten by a stale server state.

The user-facing scene snapshot is distinct from the full incident-state snapshot used for recovery. Accepted events rebuild its projection and revision. The browser remains responsible for marking unsynchronized local facts until the shared revision catches up.

## 8. AED Data and Coordination

The planned Python ETL will normalize the selected Taiwan government AED dataset, validate coordinates, deduplicate source IDs, and preserve names, addresses, opening hours, access notes, source URL, update / ingestion times, and dataset version. No AED dataset or ETL is present yet. Verify the exact source and reuse conditions before ingestion. Missing hours remain unknown, and failed imports retain the last valid dataset.

The target AED lookup will use geographic candidate filtering, such as geohash bounds with exact-distance filtering, followed by access / availability checks and walking-route estimates. PostgreSQL does not supply the AED dataset automatically. Government records may be cached locally; offline Google map tiles or route-result caching are not assumed.

The planned estimated return time includes runner → AED and AED → patient, with any retrieval-time assumption labeled separately. After collection, estimate the remaining runner → patient journey. Show estimate age and location accuracy. Maps JavaScript displays the map; Routes API calculates route data. An external navigation link may be offered, with a reminder that leaving the PWA can interrupt tracking. [Routes API](https://developers.google.com/maps/documentation/routes/compute_route_directions)

The target helper flow uses `offered`, `accepted`, `en_route`, `arrived`, `collected`, `returning`, and `delivered`, plus `unavailable`, `cancelled`, or `expired`. The current update API accepts only `accepted`, `en_route`, `arrived`, `obtained`, and `unavailable`; it checks the assigned helper and `assignmentRevision` but has no AED assignment engine.

The planned unavailable-AED flow records a reason, invalidates the old assignment, excludes that candidate for the incident, and selects the next viable destination transactionally. The current API records an `unavailable` helper status only; it does not perform reassignment. In the target flow, the helper acknowledges the updated destination. Repeated reports cannot duplicate assignments; if no candidate remains, report that no accessible candidate is known rather than recycling failed locations.

The target helper tracking and reassignment services remain independent of the Live session; the current API only records scoped helper updates. Updates remain visual in call mode. Helpers with visible connected pages can continue reporting while the primary page is offline or hidden; the primary must show those values as stale until it actually receives them.

## 9. RESTful API, Live Events, and Tools

Structured mutations pass through Flask RESTful JSON endpoints with authenticated identity, schema validation, incident scope, revisions, and idempotency. The dedicated WebSocket is only for mode-permitted Live media and control messages; it is not the general data API. Scoped REST reads provide the current canonical snapshot; clients can poll while a dedicated data subscription is absent. `agent/app/schemas/` and a checked OpenAPI specification define HTTP contracts; shared frontend types live in `web/src/types/`.

| Interface | Contract |
| --- | --- |
| `POST /v1/sessions` | Create an expiring opaque local session before authorized API writes. |
| `POST /v1/incidents` | Idempotently register a locally generated incident UUID for the authenticated primary client. |
| `WS /v1/incidents/{id}/live` | Authenticate before accepting media; return current revisions with voice disabled on every connection. The client reconciles REST events before an explicit resume. |
| `POST /v1/incidents/{id}/event-batches` | Accept bounded ordered event batches online or after an outage; return acknowledgements, conflicts, and current revisions. |
| `POST /v1/incidents/{id}/scene-observations` | Store typed observations with evidence and expected snapshot revision. Full scene-field projection is not implemented. |
| `POST /v1/incidents/{id}/location-descriptions` | Validate authorized coordinates; currently returns `503 unavailable` because geocoding is not connected. |
| `POST /v1/incidents/{id}/shares` | Create an expiring, participant-scoped invitation. |
| `POST /v1/incidents/{id}/access-revocations` | Revoke the incident’s pending invitations and active grants with an expected revision. |
| `POST /v1/share-sessions` | Bind a valid invitation to the invitee’s existing local session and create a scoped grant. |
| `POST /v1/incidents/{id}/helpers/{helperId}/updates` | Accept only the authorized helper's own location / task reports with the current assignment revision. |
| `GET /v1/incidents/{id}/aeds` | Currently returns no candidates and `dataUpdatedAt:null`; AED ingestion and routing are not connected. |
| `GET /v1/incidents/{id}/snapshot` | Return the canonical, revisioned observations to primary, greeter, or EMS. |
| `GET /v1/incidents/{id}/handoff/events` | Return a cursor-paginated, field-filtered timeline to an authorized primary or EMS session. |
| `PATCH /v1/incidents/{id}` | Change incident status with an expected revision. Closing removes active grants and blocks primary mutations; revoke pending invitations separately before closing. |

These resource-oriented paths replace the earlier `events:sync`, `location:describe`, `share-sessions:exchange`, and `close` action paths. The local API exposes these paths with the limitations stated above; the frontend has not connected them yet. Workstream 1 owns the Flask routes and contract; workstream 3 updates the shared browser client and offline sync; workstreams 2 and 4 consume the incident, helper, share, AED, and handoff operations; workstream 5 supplies the underlying data services. Existing identifiers, revision checks, error codes, and access rules remain required. For example, a client uploads a synthetic report with `POST /v1/incidents/{id}/event-batches`:

```json
{
  "events": [
    {
      "eventId": "4b7a9f79-b3b4-4a60-91cb-b958d570f3ef",
      "type": "action.reported",
      "detail": {"action": "cpr_started"},
      "clientId": "9200c811-3521-4a66-a037-9bd0bb4dc698",
      "clientInstanceId": "2bc8a203-21cc-4d95-9a0a-ef22ee924679",
      "clientSequence": 7,
      "clientTime": "2026-09-19T00:00:00Z",
      "authorityEpoch": 1,
      "stateRevision": 3,
      "modeRevision": 2,
      "ruleVersion": "demo-v1"
    }
  ]
}
```

The control envelope includes `protocolVersion`, `messageId`, `incidentId`, `clientId`, `clientInstanceId`, `clientSequence`, `clientTime`, `authorityEpoch`, `stateRevision`, `modeRevision`, and typed `payload`. The server derives `actorId` from the authenticated session. Media frames add session, sequence, mode revision, and content type. The current gateway accepts bounded PCM audio; JPEG frames return `unavailable`.

The current `EventInput` schema accepts `mode.changed`, `call.reported`, `action.reported`, `event.corrected`, `observation.proposed`, `observation.confirmed`, `command.acknowledged`, `timer.elapsed`, and `helper.updated`. `decision.committed`, `command.issued`, `incident_state.updated`, and `scene_snapshot.updated` are planned events and are rejected today. Mode events are user / browser-controller reports, not verified telephone telemetry. Snapshot updates include the revision and source-event boundary.

| Planned Agent tool | Target server behavior |
| --- | --- |
| `get_next_step(observations, expectedRevision)` | Evaluate validated observations with the pinned rules and current mode; reject stale revisions. |
| `log_event(type, detail, idempotencyKey)` | Validate an allowlisted event schema and source; do not manufacture confirmed treatment. |
| `find_nearest_aeds(lat, lng, k)` | Perform bounded geographic filtering and route / availability lookup. |
| `dispatch_helper(role)` | Create or reuse a scoped task without duplicate assignments. |
| `get_helper_status()` | Return status, freshness, and estimate provenance for the authorized incident. |
| `analyze_scene(image)` | Propose typed snapshot observations; image content cannot override instructions or issue actions. |
| `update_scene_snapshot(observations, expectedSnapshotRevision)` | Project accepted events while preserving confirmation and uncertainty. |

The tool table is target behavior; current unimplemented clinical and AED tool methods fail closed with `unavailable`. Dial-link activation, mode changes, quick-event buttons, audio gating, and metronome controls are browser actions. They do not wait for a model tool call. A model cannot place a call, claim it connected, or bypass the local gate. Expected API errors include `unauthorized`, `expired`, `stale_revision`, `rule_mismatch`, `unavailable`, and `invalid_input`, mapped to short user-facing messages.

## 10. Persistence and Permissions

### 10.1 PostgreSQL layout and current limits

The current local API stores incident state in a transactional `app_state` JSONB
row and opaque session token hashes in `local_sessions`. Row locking keeps
revision and idempotency checks consistent across Flask workers. Incident state
contains events with separate client/server times, observations, helpers,
invites, grants, and the canonical snapshot revision. Invite secrets needed for
idempotent retries are encrypted with `LOCAL_INVITE_KEY`; token and invite
lookups use hashes. This single-row storage is suitable for the small local
demo, but it serializes all incident writes and is not a normalized production
schema. Workstream 5 can replace it behind `IncidentService` without changing
the HTTP contract.

`GET /v1/incidents/{incidentId}/snapshot` returns the same typed observations
and revision to the primary, greeter, and EMS viewer. A runner cannot read it.
AED and geocoding data are not seeded or invented: AED search returns an empty
list with `dataUpdatedAt:null`, while geocoding returns `503 unavailable`.
Reviewed rule projections, MIST, AED ETL, and scheduled retention cleanup remain to be
implemented before a clinical demonstration. The current adapter denies incidents
after 72 hours and purges old state during a later successful API operation.

### 10.2 Identity and Access

The primary PWA can create an opaque local session with `POST /v1/sessions` when online and uses a local random client identity before registration succeeds. Locally created events may be uploaded only after authenticated ownership is established. A browser refresh cannot silently bind a stored incident to a different account.

QR invitations contain high-entropy secrets; lookups use hashes and retry copies are encrypted. Exchange checks expiry, redemption, and scope, then binds a scoped grant to the invitee’s independently created local session. Authentication lifetime and incident-grant lifetime are separate; a valid token alone does not grant access to every incident. Session-scoped authentication supports viewer refresh without making clinical records a persistent shared-browser cache.

| Actor | Allowed access |
| --- | --- |
| Primary session | Its incident, scene snapshot, observations / records, mode controls, and sharing operations. |
| AED runner | Its own task / location update endpoint and empty AED-candidate response; retrieval view is planned. No clinical snapshot, MIST, or complete timeline. |
| Ambulance greeter | Shared observation snapshot and its own task / location update endpoint; meeting-task view and condition / action summaries are planned. No full clinical timeline or other helpers' location histories. |
| EMS viewer | Shared observation snapshot and sanitized timeline until expiry; MIST projection is planned. No mutation permission. |
| Backend process | Validated canonical writes and projections through PostgreSQL credentials kept inside the API container. |

The browser has no direct PostgreSQL access. Flask validates session token hashes, incident ownership, grant scope, and expiry for each API read or write. An incident ID is not permission, and readable response bodies must not contain fields that their viewers should not see.

## 11. Deployment, Privacy, and Failure Handling

Docker Compose starts only `db` (PostgreSQL with a named volume) and `api` (Flask / Gunicorn). The user supplies and configures Nginx separately. The API is published at host `127.0.0.1:<API_PORT>`, with `API_PORT=8000` by default; the user-managed host Nginx on ports 80/443 proxies to that loopback address. PostgreSQL has no host port. Build the PWA with `cd web && npm ci && npm run build`; the user-managed Nginx serves `web/dist` and proxies `/v1/` and `/healthz` to the API, preserving WebSocket Upgrade. Run `./scripts/setup-local.sh` once to generate private local keys, then `docker compose up --build -d`. `PUBLIC_ORIGIN` must match the browser origin for Live WebSocket checks. A phone connecting over a LAN needs trusted HTTPS at the user-managed Nginx before browser microphone or camera access is available.

Never place long-lived Gemini credentials or private session/invitation keys in `VITE_*` variables; browser map keys must be origin- and API-restricted. A Docker deployment is local even though Gemini Live and Google Maps remain external services when enabled.

Incident state lives in PostgreSQL, not only in an ADK session or in-memory coroutine. A reconnect receives `voiceAllowed:false` and must resynchronize before the user explicitly resumes guidance. No automatic speech resume occurs.

Configuration includes model IDs, rule package versions, permitted origins, supported browser capabilities, reminder intervals, dataset / region selection, stale-data thresholds, media limits, share / grant lifetimes, and retention periods. Pin the current bundle for active incidents and keep secrets server-side.

Do not request patient names, identity numbers, or contact details. Location and medical observations remain sensitive. Raw audio, frames, and full transcripts are not retained by default; logs exclude clinical payloads, precise coordinates, and credentials. Provider data handling must be verified before claiming any retention guarantee.

Sessions, grants, and incidents have expiry checks at authorization time. A new session deletes expired session rows; a later successful incident operation purges incidents older than 72 hours and expired grants/invites. Scheduled cleanup remains an implementation gap for idle databases. Local stores are purged on open / resume and closure according to their retention rules; a closed browser cannot guarantee deletion at an exact wall-clock instant.

Helper / EMS pages keep clinical view state in memory and clear it on grant expiry or sign-out. Revocation stops future access but cannot erase information already seen. Incident closure stops media / location capture, cancels active operations, and retains only what the configured handoff and retention policies allow.

| Failure | Required behavior |
| --- | --- |
| Call state uncertain | Stay silent until the user explicitly reports dispatcher availability; never infer it from browser visibility or connectivity. |
| Backend / Live API unavailable | Continue permitted local rules and records; show remote values as stale and keep the current mode. |
| Storage unavailable or evicted | Identify missing / unsaved history, retain accessible emergency controls, and avoid fabricated recovery. |
| Camera / location / audio denied | Offer manual fields, buttons, and approved text. |
| Helper page hidden | Mark stale location / ETA from its last actual update; do not imply uninterrupted movement tracking. |
| Invalid model result | Discard it and request structured clarification. |
| Duplicate or obsolete command | Return a prior acknowledgement or reject the obsolete revision without repeating the effect. |
| Expired invitation / grant | Display an access-expired page with no incident information. |
| Reload or browser interruption | Start with audio paused, restore available state, refresh grants / data, and require explicit resume. |

Operational metrics include mode-action-to-mute latency, prohibited audio deliveries, local-save failures, snapshot lag, reconnects, synchronization conflicts, helper-data age, voice latency, and rule-validation failures. Record pseudonymous identifiers without raw medical content.

## 12. Verification and Acceptance

These are implementation requirements, not claims of existing tests or clinical validation.

| Area | Acceptance condition |
| --- | --- |
| One web application | Rescuer, runner, greeter, and EMS routes build from one Vite project and work without installation on the documented browser profiles. |
| Shared rules | Python and TypeScript pass the same cases, including unknown inputs, conflicting observations, mode interrupts, and timer changes. |
| Emergency entry | 119 access is present before permission, storage, network, or model initialization; launch is not recorded as a connected call. |
| Call-mode silence | Explicit call entry stops Agent speech, microphone upload, queued prompts, and metronome audio, including during AED reassignment. |
| Mode transitions | Call end / failure requires user reporting; redial immediately silences any clinical child flow. Visibility and network changes cannot unmute the session. |
| Media | Permission denial, blocked playback, selected-frame capture, and user-gesture activation have usable fallbacks. |
| Offline readiness | A previously prepared PWA works with network access disabled using buttons, approved content, TypeScript rules, and IndexedDB. An unprepared first visit is not claimed to work offline. |
| Recovery | Duplicate uploads, stale output, hidden tabs, reload, clock discontinuity, storage failure, and multiple-tab attempts do not silently repeat actions or overwrite the current mode. |
| Scene snapshot | Caller, greeter, and EMS show the same facts for a revision, with source / uncertainty labels and visible stale or unsynchronized state. |
| Timing | The applicable visible-page fixture delivers 120-second reminders; call mode is silent, hidden-page interruption is visible, and returning does not replay a backlog. |
| Helper loop | An inaccessible AED leads to one revised assignment and an acknowledged new destination with a fresh estimate or explicit unavailability. |
| Handoff | Snapshot appears first, followed by evidence-backed MIST and the complete paginated timeline. |
| Permissions | Cross-incident access, runner snapshot access, greeter full-timeline access, expired grants, and unauthorized writes are denied. |
| Privacy / PWA updates | Service-worker caches contain no private responses; active rule versions are preserved; expiry and interrupted synchronization behave as documented. |

Use Vitest for browser rules / controllers, pytest for services and Python rules, Playwright for route and interaction scenarios, and PostgreSQL integration checks for authorization. Physical-browser verification covers permission prompts, dialing handoff, foreground / hidden behavior, storage, and audio activation. Discover runnable commands from the implementation manifests once they exist.

Demonstration scenarios are:

1. Compare reporting completeness and duration with and without the cheat sheet using the same simulated dispatcher script.
2. Keep the rescuer and helper pages visible while recording actions, displaying the silent visual beat, tracking AED retrieval, and reassigning an inaccessible AED.
3. Manually report call end, activate voice guidance from current facts, then redial to verify immediate silence and preserved history.
4. Scan the EMS QR and identify location / access, condition, performed actions, and hazards. The target is comprehension within 10 seconds of scanning, including page access time; verify the greeter shows the same snapshot revision.
5. Disable connectivity on a prepared primary session, record updates locally, then reconnect without duplicating actions or changing call mode. Separately hide / resume the page to demonstrate the documented suspension behavior.

Use synthetic incidents, simulated calls, and a training manikin. Do not call 119 for testing. Label mocks and distinguish measured results from targets. Record the browser, device, network, model, and rule versions used in each evaluation.

## 13. Intended Repository Structure

```text
mchackathon/
├── AGENTS.md
├── README.md
├── web/                         # One React / TypeScript / Vite PWA
│   ├── public/                  # Manifest and cacheable public assets
│   └── src/
│       ├── features/
│       │   ├── rescue/          # Primary incident and reporting screens
│       │   ├── call-mode/       # Explicit mode selection and controls
│       │   ├── helpers/         # Runner and greeter routes
│       │   └── handoff/         # EMS snapshot, MIST, and timeline
│       ├── components/
│       │   ├── ui/              # Shared mobile UI
│       │   └── maps/            # Shared map presentation
│       ├── lib/
│       │   ├── media/           # Audio gate, capture, playback, and timing
│       │   ├── connection/      # Authenticated API / WebSocket clients
│       │   ├── offline/         # IndexedDB, cache lifecycle, and outbox
│       │   └── rules/           # TypeScript rule interpreter
│       └── types/               # Shared transport and domain types
├── agent/app/
│   ├── api/                     # Flask RESTful routes and Live WebSocket gateway
│   ├── agent/                   # ADK and Gemini integration
│   ├── tools/                   # Validated tool adapters
│   ├── schemas/                 # Pydantic / OpenAPI contracts
│   └── services/                # Rules, incidents, snapshots, helpers, AED data
├── rules/
│   ├── schema/
│   ├── flows/
│   ├── templates/
│   └── cases/                   # Shared Python / TypeScript fixtures
├── data/                        # AED ETL and validation
├── eval/                        # Synthetic scenario and evaluation tools
└── docs/
    └── sdd.md
```

This layout defines implementation boundaries without requiring empty scaffolding. Clinical content, reporting-field wording, actual browser profiles, model identifiers, the AED source, and retention settings remain explicit validation / configuration decisions. Coordination and ownership rules stay in `AGENTS.md`; this document specifies the product and system design.
