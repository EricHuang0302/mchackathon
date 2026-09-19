# Firestore Data Layout, Access and Retention

Firebase configuration for the First Aid Copilot incident data layer
(workstream 5). It covers Security Rules, index configuration, and the data
layout and retention rules that the backend services in
`agent/app/services/` depend on.

| File | Purpose |
| --- | --- |
| `firestore.rules` | Client access rules. Deny-by-default, read-only. |
| `firestore.indexes.json` | Composite indexes and field index exemptions. |
| `firebase.json` | Rules / index paths and the Firestore emulator port. |
| `tests/` | Security Rules tests, runnable against the emulator. |

Firebase Hosting and the AED dataset indexes are not configured here. The
`web/` build and the AED ETL do not exist on this branch, and configuring a
deploy target for code that is absent would be scaffolding, not configuration.

## Collections

```text
incidents/{incidentId}                    primary session only
  events/{eventId}                        primary session only (raw, unsanitized)
  sceneSnapshots/current                  primary, ambulance greeter, EMS viewer
  helpers/{helperId}                      primary, that helper
  helperViews/{helperId}                  primary, that helper
  handoffViews/current                    primary, EMS viewer
  grants/{uid}                            that uid only
shareInvites/{inviteId}                   no client access
aeds/{aedId}                              any signed-in client, read-only
```

Field shapes follow `docs/sdd.md` section 10.1. Scene fields carry the
provenance envelope from section 4.2: value, source, confirmation, observed
time, evidence event IDs and freshness.

### Who writes

Nothing. Every client is read-only; all canonical writes go through the
backend with the Admin SDK. Clients submit events through
`POST /v1/incidents/{id}/event-batches` and the related endpoints, which run
the ingestion, revision and authorization checks in `agent/app/services/`.

### Access matrix

| Actor | Reads | Never reads |
| --- | --- | --- |
| Primary session | Its incident, raw events, snapshot, helpers, handoff view | Another incident |
| AED runner | Its own `helpers/{id}` and `helperViews/{id}` | Snapshot, MIST, handoff view, events, other helpers |
| Ambulance greeter | The shared scene snapshot, its own task | Handoff view, raw events, other helpers' locations |
| EMS viewer | Scene snapshot, handoff view | Raw events, helper documents |

The AED runner exclusion is deliberate: a runner receives retrieval
information, not clinical information. The greeter reads the same
`sceneSnapshots/current` document as EMS so both render the same
`snapshotRevision`, but the greeter has no clinical timeline.

The equivalent checks live in `agent/app/services/access.py`
(`ROLE_CAPABILITIES`) and in the sanitized timeline allowlist in
`agent/app/services/handoff.py`. `agent/tests/test_access.py` and
`agent/tests/test_handoff.py` cover the service side; `tests/` covers the
rules side.

## Deviation from `docs/sdd.md`

`docs/sdd.md` section 10.1 shows `grants/{grantId}` with a `uid` field.
**These rules key grant documents by uid instead: `grants/{uid}`.**

Security Rules can resolve a document at a known path with `get()`, but they
cannot run a query. With a random `grantId`, a rule could not find the caller's
grant without either a query or the client passing its own grant ID, and a
client-supplied ID is not an authorization input. Keying by uid keeps the
lookup a single `get()` and makes one grant per participant per incident an
enforced invariant rather than a convention.

`AccessGrant.grant_id` is retained as a field so a grant is still traceable to
the invitation it came from.

## Admin SDK bypass

Admin SDK access runs with privileged credentials and **does not evaluate
Security Rules at all**. A rule in this file constrains browser SDK reads only.

Two consequences:

1. Every backend path must apply its own authorization. The backend resolves a
   principal with `resolve_principal()` and checks a capability before reading
   or projecting anything; passing rules tests says nothing about backend
   endpoints.
2. A rules test is not an API test. The cases in `tests/` and the cases in
   `agent/tests/test_access.py` both have to hold.

Restrict the backend service account to the minimum Firestore IAM permissions
it needs; the rules in this file will not contain it.

## Retention

Every temporary document carries `expiresAt`. Authorization denies access at
`expiresAt` even while physical deletion is still pending — `unexpired()` in
`firestore.rules` checks the incident document and the read document itself,
so an expired incident denies reads immediately.

Defaults come from `RetentionPolicy` in `agent/app/services/errors.py`:

| Scope | Default |
| --- | --- |
| Incident document | 24 h |
| Events | 24 h |
| Projections (snapshot, handoff view, helper view) | 24 h |
| Access grants | 4 h |
| Share invitations | 30 min |

### TTL policies are configured separately and do not cascade

Firestore TTL is **not** part of `firestore.indexes.json`. That file's
`fieldOverrides` are index exemptions; a TTL policy is a per-collection-group
setting applied out of band:

```bash
gcloud firestore fields ttls update expiresAt \
  --collection-group=events --enable-ttl --project=<project-id>
```

Repeat for every temporary collection group — `incidents`, `events`,
`sceneSnapshots`, `helpers`, `helperViews`, `handoffViews`, `grants` and
`shareInvites`. **A TTL policy on `incidents` does not delete anything in its
subcollections.** Deleting a parent document in Firestore does not delete its
subcollections either, so without a policy per collection group, event history
outlives the incident that produced it.

TTL deletion is also asynchronous and can lag by up to ~24 hours after the
timestamp. That is why expiry is enforced in the rules and in the services
rather than being treated as "the data is gone". Revocation likewise stops
future access but cannot retract information a viewer already saw.

The event store exposes `purge_expired()` as its only removal path, which is
the in-memory equivalent of a TTL sweep. There is no update or single-document
delete: history is append-only, and a correction is an appended event that
references the original.

## Indexes

Composite indexes in `firestore.indexes.json`:

| Collection group | Fields | Query |
| --- | --- | --- |
| `events` | `clientId`, `clientSequence` | Resume a client's outbox from its last acknowledged sequence. |
| `events` | `type`, `serverSequence` | Filtered, cursor-paginated timeline pages. |
| `helpers` | `status`, `locationUpdatedAt` | Active helpers with freshness ordering. |

Index exemptions cover `events.detail`, `sceneSnapshots.sections` and
`handoffViews.boundedTimeline`. These are arbitrary nested maps; indexing them
costs a write entry per leaf and would place clinical values into index keys
for no query benefit.

## Running the rules tests

```bash
cd firebase/tests
npm install
npm run test:emulator     # firebase emulators:exec --only firestore "node --test"
```

`test:emulator` needs the Firebase CLI **and a Java runtime**: the Firestore
emulator is a Java process.

Without `FIRESTORE_EMULATOR_HOST` set, `npm test` reports every suite as
skipped with an explicit reason. A skipped run proves nothing about the rules —
treat it as "not verified", not as "passed".

Use a `demo-` prefixed project ID (`demo-firstaid`). The emulator treats it as
a fixture project and never contacts a real Firebase project.

## Synthetic data only

Seed data in `tests/` and the scenarios in `eval/` are invented. No real
patient data, real coordinates of a real incident, credentials or clinical
logging belongs in this repository.
