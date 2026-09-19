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
`VITE_GOOGLE_MAPS_API_KEY` and optional `VITE_GOOGLE_MAPS_MAP_ID` enable the
interactive map for destinations that have coordinates. Restrict the browser
key by origin and API. Every `VITE_*` value is
browser-visible; keep Gemini credentials, session tokens, and invitation
encryption keys on the backend.

The primary rescue screens create five-minute, one-time invitations as QR
codes. Invite secrets remain in the URL fragment, are removed from the address
bar before redemption, and are never stored in a `VITE_*` value. Participant
status and throttled location updates use the scoped helper API and its returned
assignment revision.

Helper and handoff demo routes:

- `/demo/helper`: QR invitation and AED runner flow
- `/demo/ambulance`: ambulance greeter flow
- `/demo/handoff`: EMS handoff snapshot, MIST, and timeline

Set `VITE_GOOGLE_MAPS_API_KEY` in `.env.local` to enable the interactive map. Without it, the task keeps an explicit map fallback and a Google Maps navigation link.

## Ownership

- `src/features/rescue/` and `src/features/call-mode/`: rescuer flow.
- `src/lib/media/`, `src/lib/connection/`, `src/lib/offline/`, and `src/lib/rules/`: browser runtime.
- `src/features/helpers/`, `src/features/handoff/`, and `src/components/maps/`: helper and EMS experiences.
- `src/app/`, `src/components/ui/`, `src/types/`, manifests, and lockfiles are shared integration surfaces. Coordinate before editing them concurrently.

The rescuer's narrative snapshot and guidance remain synthetic and are not clinically validated. Session, incident, event, observation, sharing, scoped helper updates, empty AED responses, and EMS timeline reads use the local API. A prepared browser can reload the public shell offline and retains ordered events in IndexedDB. Geocoding, MIST, real AED/routing data, Gemini speech, Maps, installable-PWA metadata, and offline clinical rules remain unavailable.
