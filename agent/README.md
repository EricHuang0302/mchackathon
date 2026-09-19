# Agent API and local database

Flask uses the normalized PostgreSQL incident, event, snapshot, grant, rule,
and AED services by default when `DATABASE_URL` is set. `PostgresUnitOfWork`
commits event ingestion and snapshot projection in one transaction. The old
JSONB adapter can be selected with `INCIDENT_BACKEND=legacy` for a temporary
migration window; existing JSONB incidents are **not** automatically copied to
the normalized tables. The in-memory synthetic service is available only with
`SYNTHETIC_MOCK_SERVICE=1` for contract tests.

From the repository root:

```sh
./scripts/setup-local.sh
docker compose up --build -d
node scripts/smoke-local.mjs
```

Compose builds `web` and `api`, starts PostgreSQL, runs forward-only schema
migrations before the API starts, and runs retention cleanup hourly. It does
not include Nginx. `WEB_PORT` (default `8080`) and `API_PORT` (default `8000`)
publish on host loopback and can be changed in `.env`; PostgreSQL publishes no
host port. The user's host Nginx serves HTTPS on 80/443, proxies ordinary pages
to `127.0.0.1:<WEB_PORT>` and `/v1/` plus `/healthz` to
`127.0.0.1:<API_PORT>` without rewriting paths, and preserves WebSocket
Upgrade for `/v1/incidents/{id}/live`. Set `PUBLIC_ORIGIN` to the browser's
exact origin. Phone microphone/camera access needs trusted HTTPS.

The API uses local expiring bearer sessions and PostgreSQL-backed scoped
grants, with invitation secrets encrypted using `LOCAL_INVITE_KEY`. Keep
`POSTGRES_PASSWORD`, `LOCAL_INVITE_KEY`, and optional `GOOGLE_API_KEY` in the
backend environment, never in `VITE_*`. Gemini Live and Google Maps are
optional external integrations. The AED catalog must be imported separately;
Compose does not invent AED records. Without a walking-route provider the AED
service labels its estimate as a straight-line fallback, not a route or ETA.
Geocoding still returns `503 unavailable`. Optional single-frame scene analysis
uses the backend-only `GEMINI_VISION_MODEL` and `GOOGLE_API_KEY`; it is separate
from `GEMINI_MODEL` Live audio, returns only unconfirmed allowlisted proposals,
and does not retain the submitted image.

The included `demo-v1` clinical rules are marked `unreviewed_demo`. Rule
evaluation returns `503` by default so unreviewed decisions cannot appear as
approved guidance. Set `ENABLE_UNREVIEWED_DEMO_RULES=1` only for a synthetic
training demonstration; responses still carry `clinicalReviewRequired:true`.
The TypeScript interpreter now exists and runs shared fixtures; clinical review
and complete offline product wiring remain separate work.

For API checks with Python 3.12 from `agent/`:

```sh
python -m venv .venv
.venv/bin/pip install -e '.[test,live]'
PYTHONPATH=. .venv/bin/python scripts/generate_openapi.py --check
PYTHONPATH=. .venv/bin/pytest -q
```

`PG_TEST_DSN` and `NORMALIZED_API_TEST_DSN` enable real PostgreSQL tests. Use a
**dedicated synthetic test database**; `PG_TEST_DSN` tests drop the `app_state`
and `local_sessions` tables. Outside Compose, run
`python -m app.services.postgres_data migrate` before starting Flask and
`python -m app.services.postgres_data cleanup` periodically with `DATABASE_URL`
set. Authorization checks expiry immediately; cleanup performs delayed physical
deletion. Existing JSONB data requires a separate migration or the temporary
`INCIDENT_BACKEND=legacy` setting.

See [INTEGRATION.md](INTEGRATION.md) for endpoint payloads, permissions,
revision and error behavior, Live messages, and remaining consumer work. Tests
use synthetic incidents and never dial 119.
