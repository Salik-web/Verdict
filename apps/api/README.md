# @geo/api — TypeScript API (Fastify)

Auth, account/CRUD, dashboard data, billing, scheduling. Triggers the Python
pipeline over authenticated internal HTTP. BullMQ+Redis for TS-side jobs,
Drizzle ORM over the shared Postgres. (Phase 1 ships only health + the internal
client wiring — no business logic yet.)

## Run

From the **repo root** (pnpm workspace):

```bash
corepack enable
pnpm install
cp apps/api/.env.example apps/api/.env   # adjust if needed
pnpm --filter @geo/api dev               # http://localhost:3000
```

Build / lint:

```bash
pnpm --filter @geo/api build
pnpm --filter @geo/api lint
```

## Endpoints

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/health` | none | Liveness; returns the shared `HealthResponse` shape. |
| GET | `/internal/pipeline-health` | none (server-side) | Calls the pipeline's protected `/internal/ping` via the shared-secret client. Proves the authenticated internal path. |

## Config

All env vars are in [`.env.example`](.env.example) and validated by Zod in
[`src/config.ts`](src/config.ts) at boot. `INTERNAL_SHARED_SECRET` must match the
pipeline service. Secrets are never logged.

## Internal client

[`src/internal/pipeline-client.ts`](src/internal/pipeline-client.ts) is the typed
client for the pipeline's internal endpoints. It attaches the
`x-internal-secret` header (from `@geo/shared`) to every request. Trigger
endpoints for the Monitor → Diagnose → Execute → Verify stages get added here in
later phases.
