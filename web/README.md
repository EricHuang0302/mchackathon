# First Aid Copilot Web

Single React / TypeScript / Vite application for the rescuer, helper, and EMS handoff routes.

## Commands

```bash
npm install
npm run dev
npm run lint
npm run typecheck
npm test
npm run build
```

Build with `npm ci && npm run build`. Compose builds the same production assets
and serves them with `server.mjs`, including SPA fallback and same-origin proxying
for local smoke tests. Production host Nginx remains user-managed. Shared REST,
session, IndexedDB outbox, Live socket, and media-gate code is in
`src/lib/connection/`, `src/lib/offline/`, and `src/lib/media/`; feature screens
do not create independent transports.
`VITE_GOOGLE_MAPS_API_KEY` in `.env.example` is a reserved browser-visible
placeholder, not a value currently read by the UI. If Google Maps is added,
restrict its browser key by origin and API. Every `VITE_*` value is
browser-visible; keep Gemini credentials, session tokens, and invitation
encryption keys on the backend.

## Ownership

- `src/features/rescue/` and `src/features/call-mode/`: rescuer flow.
- `src/lib/media/`, `src/lib/connection/`, `src/lib/offline/`, and `src/lib/rules/`: browser runtime.
- `src/features/helpers/`, `src/features/handoff/`, and `src/components/maps/`: helper and EMS experiences.
- `src/app/`, `src/components/ui/`, `src/types/`, manifests, and lockfiles are shared integration surfaces. Coordinate before editing them concurrently.

The rescuer's narrative snapshot and guidance remain synthetic and are not clinically validated. Session, incident, event, observation, sharing, scoped helper updates, empty AED responses, and EMS timeline reads use the local API. A prepared browser can reload the public shell offline and retains ordered events in IndexedDB. Geocoding, MIST, real AED/routing data, Gemini speech, Maps, installable-PWA metadata, and offline clinical rules remain unavailable.
