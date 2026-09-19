# First Aid Copilot Web

Single React / TypeScript / Vite application for the rescuer, helper, and EMS handoff routes.

## Commands

```bash
npm install
npm run dev
npm run typecheck
npm test
npm run build
```

Build with `npm ci && npm run build` and serve `dist/` through the user-managed Nginx; this repository does not configure that Nginx. API requests use the same origin and `/v1` paths; `VITE_API_BASE_URL` is optional for separate Vite development. Only the optional Google Maps browser key belongs in `VITE_GOOGLE_MAPS_API_KEY`, and it must be restricted by origin and API. Every `VITE_*` value is browser-visible; keep Gemini credentials, session tokens, and invitation encryption keys on the backend.

## Ownership

- `src/features/rescue/` and `src/features/call-mode/`: rescuer flow.
- `src/lib/media/`, `src/lib/connection/`, `src/lib/offline/`, and `src/lib/rules/`: browser runtime.
- `src/features/helpers/`, `src/features/handoff/`, and `src/components/maps/`: helper and EMS experiences.
- `src/app/`, `src/components/ui/`, `src/types/`, manifests, and lockfiles are shared integration surfaces. Coordinate before editing them concurrently.

The current screens use explicit demo data. They do not represent a connected emergency service or clinically validated workflow.
