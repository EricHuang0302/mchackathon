# Local deployment

Run all commands from the repository root. Install Docker with Compose, Python 3, and Node.js, and use a POSIX-compatible shell for the setup script. For frontend development, use a Node.js version supported by the installed Vite release (20.19+ or 22.12+).

## Start the stack

```sh
./scripts/setup-local.sh
docker compose up --build -d
node scripts/smoke-local.mjs
```

The setup script creates `.env` with local database and invitation keys. It preserves an existing `.env`. Review the configuration before starting the stack.

Docker Compose starts `web`, `api`, and `db`, runs database migrations before the API starts, and schedules hourly retention cleanup. The web image builds the Vite production assets and serves them with a lightweight Node HTTP server and SPA fallback. PostgreSQL is accessible only within the Compose network.

By default, the web application is available at `http://127.0.0.1:8080` and the API at `http://127.0.0.1:8000`. Set `WEB_PORT` and `API_PORT` in `.env` to change these host ports.

## Phone access and HTTPS

Phone access requires a trusted HTTPS origin. Set `PUBLIC_ORIGIN` to the actual URL opened on the phone, such as `https://rescue.example`.

Nginx is managed separately on the host. Configure one `location /` proxy to `127.0.0.1:<WEB_PORT>` and forward `Upgrade`, `Connection`, `Host`, and `X-Forwarded-Proto`. The web server forwards `/v1/`, `/healthz`, and the Live WebSocket to the API on the same origin; do not split those paths into a separate Nginx proxy to the API port. Compose does not bind ports 80 or 443.

## Import AED data

After the stack starts, import a Ministry of Health and Welfare-format AED CSV:

```sh
docker compose run --rm aed-import
```

The default input is `AED20260919.csv` in the repository root, with dataset version `AED20260919`. Set `AED_CSV_PATH` and `AED_DATASET_VERSION` in `.env` to use another local file and version. The importer validates the complete dataset before atomically replacing the active data.

Without a routing provider, estimates are labeled as straight-line distances, not walking routes or arrival times.

## Configure Gemini and Maps

Set `GOOGLE_API_KEY`, `GEMINI_TRANSCRIBE_MODEL`, `GEMINI_TEXT_MODEL`, and `GEMINI_VISION_MODEL` on the backend for Gemini Live transcription, structured extraction, and single-image analysis. These flows include human confirmation, task planning, and bounded AED/helper tools. Keep backend credentials out of browser configuration.

Set `VITE_GOOGLE_MAPS_API_KEY` for frontend task maps and optionally `VITE_GOOGLE_MAPS_MAP_ID` for a Map ID. Restrict the browser key to the intended origins and APIs. Rebuild the web image after changing these values because `VITE_*` configuration is included in the browser bundle.

## Demo rules and implementation limits

The `demo-v1` rules have not undergone clinical review, so evaluation is disabled by default. Set `ENABLE_UNREVIEWED_DEMO_RULES=1` only for synthetic training demonstrations.

The backend supports local identity, incidents and events, transactional snapshot projection, sharing and grants, AED lookup and reassignment, MIST, handoff timelines, and pinned-version Python rule evaluation. AED data must be imported separately. Geocoding and the complete offline PWA remain unfinished.

See the [backend integration guide](../agent/INTEGRATION.md) for API details and current limitations, or return to the [project overview](../README.md).
