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

Copy `.env.example` to `.env.local` for local provider configuration. Every `VITE_*` value is visible to the browser; never put Gemini credentials, service-account keys, invitation secrets, or other privileged values there.

## Ownership

- `src/features/rescue/` and `src/features/call-mode/`: rescuer flow.
- `src/lib/media/`, `src/lib/connection/`, `src/lib/offline/`, and `src/lib/rules/`: browser runtime.
- `src/features/helpers/`, `src/features/handoff/`, and `src/components/maps/`: helper and EMS experiences.
- `src/app/`, `src/components/ui/`, `src/types/`, manifests, and lockfiles are shared integration surfaces. Coordinate before editing them concurrently.

The current screens use explicit demo data. They do not represent a connected emergency service or clinically validated workflow.
