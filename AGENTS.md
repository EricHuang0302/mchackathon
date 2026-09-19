# Repository Working Agreements

These rules apply to contributors and coding agents across this repository. Follow explicit user instructions for the current task, and read any applicable directory-specific instructions before editing. Keep coordination lightweight and proportional to this hackathon prototype.

## Current Architecture

- Product principle: **the dispatcher leads; the Agent assists**. Read [README.md](README.md) for the Traditional Chinese introduction.
- The target implementation is one **React + TypeScript + Vite PWA** in `web/`, covering the primary rescuer, helpers, and EMS handoff through separate routes. The current frontend has synthetic demo flows; installable/offline PWA behavior is not implemented.
- The backend uses **Python 3.12, Flask, Google ADK, and Google Gemini** in `agent/`. Structured application operations use RESTful JSON through the user-managed reverse proxy; a dedicated WebSocket carries Live media and control messages. Trusted HTTPS is required for phone access over a LAN. PostgreSQL provides local persistence and scoped reads; Docker Compose runs the API and PostgreSQL. The user manages Nginx separately. Gemini Live and Google Maps are optional external integrations.
- Shared clinical rules are planned as declarative YAML. When implemented, Python evaluates them online and TypeScript evaluates the same supported subset offline using shared fixtures.
- Planned offline scope is cached approved content, button-driven rules, IndexedDB records, and synchronization on return. On-device Gemma, a Kotlin app, React Native, and native wrappers are outside the current baseline unless the user changes the scope.
- Call mode is controlled through explicit UI actions. The hackathon prototype opens the configured test link `tel:0979796806`, never `tel:119`, and first mutes the Agent; launching the link records only an attempted call. A user action confirms connection, reports that dispatcher guidance ended, or reports that the call was unavailable. Do not promise automatic telephone-state detection or automatic speakerphone control from the browser.
- The supported demonstration assumes the relevant pages remain in the foreground. Page visibility is not telephone state. Background or locked-screen tracking, camera capture, and precise timers are not guaranteed.
- [docs/sdd.md](docs/sdd.md) defines the current React / PWA architecture, browser capability limits, product behavior, and data contracts. Keep it consistent with this baseline when changing cross-module behavior; this file defines collaboration and implementation rules.
- Directory assignments below describe intended boundaries. Inspect the actual tree and manifests before assuming a component, dependency, or command exists. Do not scaffold unrelated areas just to populate the structure.

## Five-Person Module Boundaries

The numbers identify workstreams, not named maintainers. Use the user's current assignment to determine which workstream a contributor is handling.

| Workstream | Primary paths | Responsibilities |
| --- | --- | --- |
| 1. Agent and API | `agent/app/api/`, `agent/app/agent/`, `agent/app/tools/`, `agent/app/schemas/` | Flask RESTful endpoints, Live WebSocket protocol, ADK / Gemini integration, tool adapters, API payload validation, and backend entry points. |
| 2. Rescuer UI and flow | `web/src/features/rescue/`, `web/src/features/call-mode/`, `web/src/components/ui/` | Dial-first screen, reporting cheat sheet, quick-event controls, interaction modes, shared UI primitives, and application shell / route integration. |
| 3. Browser runtime | `web/src/lib/media/`, `web/src/lib/connection/`, `web/src/lib/offline/`, `web/src/lib/rules/` | Audio / camera adapters, local audio gate, WebSocket client, timing, IndexedDB outbox, service worker, and TypeScript rule interpreter. |
| 4. Helpers and handoff | `web/src/features/helpers/`, `web/src/features/handoff/`, `web/src/components/maps/` | QR entry, helper tasks, browser location reporting, map / route display, ambulance-greeter snapshot, and EMS handoff page. |
| 5. Rules and data services | `rules/`, `data/`, `eval/`, `agent/app/services/` | Python rule interpreter, approved templates, shared fixtures, AED ETL / search / route estimates / reassignment, persistence, snapshot projection, access grants, and retention. |

- Workstream 1 exposes APIs and tools over workstream 5 services; do not duplicate database, AED-ranking, or clinical-rule logic in tool wrappers.
- Workstreams 2 and 4 use shared clients from workstream 3. Avoid independent socket managers, authentication clients, audio players, or offline stores inside feature components.
- Workstream 2 owns mode selection and presentation; workstream 3 enforces the corresponding audio / media policy. Workstream 5 defines clinical rules. Keep these responsibilities separate.
- Workstreams 3 and 5 maintain interpreter parity. A new rule operator is incomplete until both runtimes support it and the shared cases pass.
- All frontend contributors use one Vite application, dependency manifest, lockfile, routing system, and set of shared types. Do not create separate frontend projects for each participant.

## Coordination and Shared Files

1. Before editing, inspect `git status`, the current branch, relevant instructions, nearby code, and existing task context. State the intended scope, paths, and interface dependencies in the current task or existing coordination channel.
2. Use a separate branch and checkout / worktree for concurrent contributors when possible. Never switch branches, reset, or stash another contributor's active shared checkout.
3. Keep one active writer per shared file. Coordinate overlapping edits to routes, shared types, schemas, global styles, manifests, lockfiles, local deployment configuration, or root documentation before editing the same file concurrently.
4. Module ownership is a coordination default, not an approval gate for every small repair. A necessary change outside the assigned area must be minimal, identified in the handoff, and compatible with its consumers. If someone is actively editing it, leave that file alone and continue independent work until the overlap is resolved.
5. Shared API / WebSocket types belong to workstream 1 with frontend consumers involved; rule schemas and fixtures belong to workstream 5 with workstream 3 involved. The frontend shell and common UI belong to workstream 2; local API/database deployment configuration belongs to workstream 5; Nginx configuration belongs to the user.
6. Record a cross-module interface change in the existing task or PR with the affected fields, consumers, compatibility behavior, and an example payload. Do not leave a breaking producer change for another person to discover during integration.
7. When a dependency is unavailable, use a typed, clearly labeled mock matching the agreed contract. Keep a real integration path and identify what remains mocked. Do not simulate successful medical actions, authentication, or live tracking without labeling them.
8. Preserve other contributors' work. Do not overwrite unexplained edits, remove files outside the task, or perform broad formatting changes. Resolve conflicts by understanding both changes, not by accepting an entire side.
9. Use existing task context and PRs for coordination. Do not create `.ai-team/`, agent-workflow directories, scratch plans, or tracking files in the repository. Temporary notes belong outside the repository; requested deliverables belong in established project paths.
10. Do not automatically launch agents or create user-visible tasks because this project has five workstreams. Use delegation only when requested or authorized for the current work, with a bounded scope and clear file boundaries.

## Contracts and Integration Rules

- Define or update the contract before connecting a producer and consumer. Specify required fields, enums, null / unknown behavior, error responses, permissions, and example events.
- Treat `agent/app/schemas/` and a checked OpenAPI specification for Flask routes as the HTTP contract source. Keep frontend transport types in one shared location, such as `web/src/types/`; generate or check them against that source instead of maintaining feature-local copies. Use RESTful JSON endpoints for structured operations and reserve WebSocket for the Live media / control stream.
- Put rule / observation schemas in `rules/schema/` and cross-runtime cases in `rules/cases/`. Parse a restricted YAML subset; reject unknown operators, duplicate keys, and invalid transitions. Never evaluate arbitrary code from rules.
- Shared interaction modes are `call_119`, `on_call`, `voice_guidance`, and `handover`. Keep interaction mode separate from clinical state, connection state, and incident status.
- Preserve identifiers and revisions across boundaries: `incidentId`, `eventId`, `ruleVersion`, `stateRevision`, `modeRevision`, `snapshotRevision`, and `authorityEpoch` where applicable. Do not replace explicit concurrency checks with unqualified last-write-wins updates.
- Use stable event IDs and idempotent mutations. Store occurrence / client time separately from server receipt time; retain local event order and clock uncertainty. Corrections append a referenced event instead of silently rewriting history.
- Pin a rule version per incident. Python and TypeScript must agree on state, template, action, and timer output for the same inputs; `unknown` must not become `false`.
- Maintain one canonical scene snapshot with field provenance, uncertainty, revision, and freshness. The cheat sheet, greeter, and EMS views render the same facts; they must not ask separate models to invent independent summaries.
- Prefer additive contract changes. If a breaking change is necessary, update affected callers, fixtures, documentation, and compatibility handling together or provide an explicitly coordinated migration.
- Keep provider details behind adapters. UI components must not contain Gemini prompts, unrestricted API keys, direct clinical branching, or direct privileged database writes.

## Product Invariants

- The first screen exposes 119 access with a short scene-safety reminder and speakerphone instructions. Registration, permissions, GPS, and model startup must not block it.
- In `on_call`, immediately stop Agent speech, queued audio, microphone upload, spoken reminders, and metronome audio. Keep factual screen updates, quick records, helper coordination, and a foreground visual beat available.
- The browser's local audio gate wins over the backend and model. Tag delayed commands / voice output with mode revisions and discard stale output. A reconnect, page resume, or network loss must never automatically unmute an ongoing or uncertain call.
- Voice guidance is allowed only after dispatcher guidance has ended or an attempted call could not connect, with explicit user mode controls for the PWA. Preserve treatment history when switching modes and never replay accumulated prompts.
- Models propose observations and bounded wording; reviewed rules select clinical steps. Critical instructions come from approved templates. Do not introduce improvised treatment advice or present unreviewed content as clinically validated.
- Distinguish recommended actions, user-reported actions, device acknowledgements, and uncertain observations. A button tap is a report, and an issued instruction does not establish that treatment happened.
- AED dispatch and reassignment must work without a Live voice session. Show stale positions and estimates honestly; distinguish straight-line distance from a walking route or ETA.
- Show the scene snapshot above MIST and the full timeline on handoff. A greeter may read the shared snapshot; an AED runner receives only retrieval information. A QR scan does not prove EMS has taken over.
- Demonstrations use synthetic incidents and simulated dispatchers. Do not place real emergency calls to test a flow or use real patient data in fixtures, screenshots, logs, or recordings.

## Data, Credentials, and Dependencies

- Derive identity and permissions from authenticated sessions, never a model-supplied role or incident ID. Validate scope in backend APIs and PostgreSQL-backed grants.
- Keep long-lived Gemini credentials and backend credentials on the backend. `VITE_*` configuration is browser-visible; never put secrets there. Restrict browser map keys to the intended origins and APIs.
- Keep invitation secrets, raw media, medical payloads, and exact coordinates out of ordinary logs. Use synthetic data for development and avoid storing raw audio / video by default.
- Share links and access grants must expire and support revocation. Access expiry is independent of asynchronous physical deletion. Apply retention to incident records, local outbox / snapshots, and transient shared-browser state.
- Add dependencies only for a concrete task need. Reuse the established package manager and framework; keep one lockfile per package ecosystem and update it with its manifest using that package manager. Do not replace manifests or hand-resolve lockfiles by dropping another contributor's dependencies.
- Do not add Redis, extra databases, native wrappers, model downloads, or new deployment services merely to satisfy a hypothetical future need. Keep the hackathon implementation focused on the accepted demonstration.

## Git and Delivery

- Default collaborative implementation to a focused task branch and PR targeting `main`. Follow explicit user authorization for direct commits / pushes to `main`, including authorization already given for the same documentation work. Do not add a redundant approval step.
- Inspect the diff and stage only files or hunks belonging to the task. Never use a blanket commit that includes another contributor's changes.
- Fetch before integration. If `main` advances, incorporate its changes and rerun affected checks; do not force-push `main` or rewrite shared history.
- Keep commits focused. Use English Conventional Commits: `<type>: <lowercase imperative summary>`, with no trailing period. Allowed types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `build`, `ci`, `style`, `revert`.
- PR titles follow the same format. PR bodies are English with `Summary`, `Changes`, and `Testing`; add `Notes` only for relevant limitations or migration details.
- Do not add co-author trailers, AI / tool attribution, generated-by signatures, or emojis to commits or PR bodies.
- Include changed behavior, affected contracts, checks run, and remaining limitations in the delivery note. State whether work is committed, pushed, or still local. Do not report a remote update as successful without a successful push result.

## Verification and Completion

Discover commands from actual manifests and existing documentation. The repository may initially contain only documentation: do not claim that `npm test`, `pytest`, a build, or CI passed when that setup does not exist.

| Change | Required verification when the relevant implementation exists |
| --- | --- |
| Frontend behavior | Relevant type / lint / build scripts and focused interaction checks; verify the affected mobile route and its loading, denied-permission, and error states. |
| Media or mode control | Verify call-mode entry during playback, queued-output cancellation, explicit resume, redial, page visibility changes, and reconnection. |
| Rule changes | Run the affected shared fixtures in Python and TypeScript, including unknown inputs and mode interrupts. |
| API / event changes | Check producer-consumer payload compatibility, authentication, error handling, duplicate delivery, and stale revisions. |
| Offline changes | Check local persistence, interrupted synchronization, retry deduplication, snapshot freshness, and preservation of the current mode. |
| Access / persistence changes | Use service and PostgreSQL integration checks for cross-incident denial, runner / greeter / EMS permissions, grant expiry, and retention behavior. |
| AED / handoff changes | Exercise unavailable-AED reassignment, stale location / ETA, matching scene-snapshot revisions, and the snapshot-first handoff. |
| Documentation only | Check accuracy, relative links, Markdown structure, and whitespace; no application test suite is required. |

- Test the changed behavior and important failure cases; do not add tests that only mirror implementation details or expand a small task into unrelated test work.
- Shared contract, rule, or permission changes require the relevant consumer checks, not just the producer's tests. Keep fixtures synthetic and deterministic.
- Finish with a reviewed diff, appropriate checks, consistent documentation for changed contracts, and a clear handoff. If a check cannot run, report the exact limitation and what was verified instead.

## Language and Communication

- Chat with the user in Traditional Chinese. Keep updates concise and state concrete findings or blockers.
- Write code identifiers, comments, specifications, commit messages, and PRs in English by default. Preserve the explicitly requested Traditional Chinese README and user-facing `zh-TW` content.
- Continue routine, authorized implementation and verification without repeated approval requests. Ask only when a material ambiguity changes scope or correctness; continue independent work while waiting.
- Keep this file focused on durable rules. Product detail belongs in `docs/`; task-specific progress belongs in the existing task or PR, not in this file.

Instruction-file reference: [official OpenAI guidance for AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md).
