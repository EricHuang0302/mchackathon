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

Build with `npm ci && npm run build` and serve `dist/` through the user-managed
Nginx; this repository does not configure that Nginx. The shared browser client
should call same-origin `/v1` REST routes and `/v1/incidents/{id}/live` WebSocket
as specified in [the backend integration guide](../agent/INTEGRATION.md).
There is **no API client or Live socket manager in `web/src` yet**.
`VITE_API_BASE_URL` and `VITE_GOOGLE_MAPS_API_KEY` in `.env.example` are reserved
placeholders, not values currently read by the UI. If Google Maps is added,
restrict its browser key by origin and API. Every `VITE_*` value is
browser-visible; keep Gemini credentials, session tokens, and invitation
encryption keys on the backend.

## Ownership

- `src/features/rescue/` and `src/features/call-mode/`: rescuer flow.
- `src/lib/media/`, `src/lib/connection/`, `src/lib/offline/`, and `src/lib/rules/`: browser runtime.
- `src/features/helpers/`, `src/features/handoff/`, and `src/components/maps/`: helper and EMS experiences.
- `src/app/`, `src/components/ui/`, `src/types/`, manifests, and lockfiles are shared integration surfaces. Coordinate before editing them concurrently.

The current screens use explicit demo data. They do not represent a connected emergency service or clinically validated workflow.
