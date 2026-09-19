# Agent API and local database

The Flask API validates Pydantic requests in `app/schemas/contracts.py`; the
checked HTTP contract is `openapi.json`. `app/api/auth.py` stores opaque session
token hashes. `app/services/postgres.py` persists incidents, events, revisions,
observations, helpers, invites, and grants in PostgreSQL. It serializes the
current prototype state in one JSONB row under a row lock, so the data survives
API restarts. Concurrent workers cannot bypass revision checks. The normalized
workstream 5 schema and repository adapters live in
`app/services/postgres_data/`; the Flask `IncidentService` still uses the JSONB
adapter until workstream 1 connects those repositories to the HTTP application
service.

The repositories keep each operation short and transactional. The existing
`IncidentEventService` calls event append and incident projection update as two
store operations, so selecting the normalized adapters directly would not make
that pair atomic. The active integration must add an application-level unit of
work (or an equivalent transactional ingestion service) before replacing the
JSONB adapter.

Start the API and database from the repository root:

```sh
./scripts/setup-local.sh
docker compose up --build -d
```

The API listens on host `127.0.0.1:8000` by default; set `API_PORT` in `.env`
to choose another host port. PostgreSQL has no host port. Your host Nginx
proxies to `127.0.0.1:<API_PORT>`. Build the PWA with
`cd web && npm ci && npm run build`, then serve `web/dist` from your own Nginx.
Proxy `/v1/` and `/healthz` to Flask and preserve WebSocket Upgrade for
`/v1/incidents/{id}/live`. This repository does not provide Nginx configuration.
The generated `.env` holds the database password and invitation encryption key;
keep it with the database volume. Set `PUBLIC_ORIGIN` to the exact browser
origin. Phone access over a LAN requires trusted HTTPS before using microphone
or camera APIs. Optional `GEMINI_MODEL` and `GOOGLE_API_KEY` stay in the API
container. Google Maps keys are browser-visible and must be restricted to the
intended origin and APIs.

For API checks with Python 3.12:

```sh
python -m venv .venv
.venv/bin/pip install -e '.[test,live]'
PYTHONPATH=. .venv/bin/python scripts/generate_openapi.py --check
PYTHONPATH=. .venv/bin/pytest -q
```

Apply the forward-only normalized schema explicitly. The command records each
applied version and is safe to rerun:

```sh
DATABASE_URL=postgresql://... PYTHONPATH=.:.. .venv/bin/python -m app.services.postgres_data migrate
```

Run retention from cron, a host timer, or an explicit Docker command. It deletes
expired normalized rows and also cleans the active legacy JSONB state when
`LOCAL_INVITE_KEY` is supplied:

```sh
DATABASE_URL=postgresql://... LOCAL_INVITE_KEY=... \
  PYTHONPATH=.:.. .venv/bin/python -m app.services.postgres_data cleanup
```

Expiry is enforced at authorization time; this command only performs delayed
physical deletion. Do not run migrations or cleanup against a database whose
contents you have not identified.

`PG_TEST_DSN` enables the real PostgreSQL integration test. It drops the
`app_state` and `local_sessions` tables in that **dedicated test database**.
Do not point it at a database containing data. The synthetic in-memory service
is available only with `SYNTHETIC_MOCK_SERVICE=1`; it is for contract tests.

`POST /v1/sessions` creates an expiring opaque local token. All other `/v1`
HTTP routes require `Authorization: Bearer <sessionToken>`. The first Live
WebSocket JSON message also carries this token. Local session tokens are stored
as hashes, and invite secrets retained for idempotent retries are encrypted in
PostgreSQL. Sessions, grants, and incidents are checked at access time; incident
data is purged after 72 hours on a later successful API operation or by the
explicit cleanup command. The primary can revoke all pending invitations and
active grants with `POST /v1/incidents/{id}/access-revocations`.

Current integrations return honest unavailable data: AED list is empty with
`dataUpdatedAt:null`, location description returns `503`, and unimplemented
clinical tools fail closed. The frontend screens are still static demo screens;
workstreams 2–4 must connect them to these APIs. No real 119 call is made in
tests. See [INTEGRATION.md](INTEGRATION.md) for exact consumer URLs, payloads,
permissions, Live messages, and workstream handoff.
