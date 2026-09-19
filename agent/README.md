# Agent API and local database

The Flask API validates Pydantic requests in `app/schemas/contracts.py`; the
checked HTTP contract is `openapi.json`. `app/services/postgres.py` persists
sessions, incidents, events, revisions, observations, helpers, invites, and
grants in PostgreSQL. It serializes the current prototype state in one JSONB
row under a row lock, so the data survives API restarts and concurrent workers
cannot bypass revision checks. This is a small local demo design; workstream 5
can replace it with normalized services behind `IncidentService`.

Start the whole project from the repository root:

```sh
./scripts/setup-local.sh
docker compose up --build
```

Open `http://localhost:8080`. Nginx serves the single Vite build and proxies
`/v1/` REST and Live WebSocket traffic to Flask; PostgreSQL has no host port.
The generated `.env` holds the database password and invitation encryption key.
For phone access over a LAN, put trusted HTTPS at Nginx and set `PUBLIC_ORIGIN`
to the exact HTTPS origin before using microphone or camera APIs. Optional
`GEMINI_MODEL` and `GOOGLE_API_KEY` stay in the API container. Google Maps keys
are browser-visible and must be restricted to the intended origin and APIs.

For API checks with Python 3.12:

```sh
python -m venv .venv
.venv/bin/pip install -e '.[test,live]'
PYTHONPATH=. .venv/bin/python scripts/generate_openapi.py --check
PYTHONPATH=. .venv/bin/pytest -q
```

`PG_TEST_DSN` enables the real PostgreSQL integration test. It drops the
`app_state` and `local_sessions` tables in that **dedicated test database**.
Do not point it at a database containing data. The synthetic in-memory service
is available only with `SYNTHETIC_MOCK_SERVICE=1`; it is for contract tests.

`POST /v1/sessions` creates an expiring opaque local token. All other `/v1`
HTTP routes require `Authorization: Bearer <sessionToken>`. The first Live
WebSocket JSON message also carries this token. Local session tokens are stored
as hashes, and invite secrets retained for idempotent retries are encrypted in
PostgreSQL. Sessions, grants, and incidents are checked at access time; incident data is purged after 72 hours on a later successful API operation. The primary can revoke all pending invitations and active grants with `POST /v1/incidents/{id}/access-revocations`.

Current integrations return honest unavailable data: AED list is empty with
`dataUpdatedAt:null`, location description returns `503`, and unimplemented
clinical tools fail closed. The frontend screens are still static demo screens;
workstreams 2–4 must connect them to these APIs. No real 119 call is made in
tests. See [INTEGRATION.md](INTEGRATION.md) for payloads and permissions.
