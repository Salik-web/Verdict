# @geo/api — TypeScript API (Fastify)

Auth, account/CRUD, dashboard data, billing hooks, and the pipeline trigger.
Talks to the frontend; calls the Python pipeline over authenticated internal
HTTP. Drizzle over the shared Postgres, Redis for sessions + rate limits.

## Run

From the **repo root** (pnpm workspace):

```bash
corepack enable
pnpm install
cp apps/api/.env.example apps/api/.env   # adjust if needed
pnpm --filter @geo/api dev               # http://localhost:3000
```

Build / lint / test:

```bash
pnpm --filter @geo/api build
pnpm --filter @geo/api lint
pnpm --filter @geo/api test    # checkpoint suite (needs infra + pipeline up)
```

## Database

The shared Postgres schema lives in [`/db`](../../db/) (SQL is the source of
truth; see [SCHEMA.md](../../db/SCHEMA.md)). This service owns the migration +
seed runners and mirrors the schema in Drizzle ([src/db/schema.ts](src/db/schema.ts)).

```bash
pnpm --filter @geo/api db:migrate   # apply pending SQL migrations (idempotent)
pnpm --filter @geo/api db:seed      # load the demo account (idempotent)
pnpm --filter @geo/api db:check     # read the demo account via repositories
```

All DB access goes through the repository layer in [src/repositories/](src/repositories/)
— tenant-scoped (every query filters on `account_id`), no raw SQL in business
logic.

## Auth & tenant isolation

Local email+password auth behind an `AuthService` interface
([src/auth/service.ts](src/auth/service.ts)) — Clerk/Supabase can slot in later
via config, same swappability pattern as the model gateway. Zero external keys
needed (mock-first).

- **Passwords:** argon2id (OWASP parameters). Uniform-timing login (dummy hash
  for unknown emails).
- **Sessions:** opaque ids in **signed httpOnly cookies**; state in Redis.
  Short-lived session (15 min) + refresh token (14 d) with **rotation**: each
  refresh consumes the token (atomic GETDEL) and issues a new pair; a replayed
  refresh token revokes the whole token family.
- **Tenant isolation:** `requireAuth` resolves `{userId, accountId}` from the
  session; every handler takes `account_id` from there — never from the URL or
  body. Resource lookups are `(accountId, id)` pairs, so another tenant's ids
  read as 404 (no IDOR, no existence leak).
- Email verification + MFA: interface hooks present; they need an external
  provider (keys), so they land with the Clerk adapter or a later phase.

## Security baseline

- **Headers:** helmet — CSP (`default-src 'none'`), HSTS, `X-Frame-Options: DENY`.
- **CORS:** locked to `FRONTEND_ORIGIN`, credentials mode, never `*`.
- **Rate limiting:** Redis-backed. Default 100 req/min/IP; `/auth/*` endpoints
  5/min (login/signup) and 10/min (refresh). 429 responses carry `Retry-After`.
- **Usage quotas:** keyed to the account's **plan** via
  [config/plans.json](config/plans.json) (data-driven). `POST /scans` enforces
  `scans_per_day` (this is also the cost cap); prompts/competitors have
  `max_*` ceilings.
- **Validation:** Zod on every route (body, params, query) — 400 with field
  detail on failure.
- **Secrets at rest:** CMS credentials use **envelope encryption**
  ([src/crypto/envelope.ts](src/crypto/envelope.ts)): per-row AES-256-GCM data
  key, wrapped by `MASTER_ENCRYPTION_KEY` (KEK) from env. API responses return
  metadata only — never credential material or ciphertext.
- **Audit:** signup/login, scan triggers, CMS credential create/delete write
  `audit_logs` rows.

## Endpoints

| Method          | Path                                               | Auth               | Purpose                                                                     |
| --------------- | -------------------------------------------------- | ------------------ | --------------------------------------------------------------------------- |
| GET             | `/health`                                          | none               | Liveness.                                                                   |
| POST            | `/auth/signup`                                     | none (strict RL)   | Create account + owner user; sets session cookies.                          |
| POST            | `/auth/login`                                      | none (strict RL)   | Login; sets session cookies.                                                |
| POST            | `/auth/refresh`                                    | refresh cookie     | Rotate the session/refresh pair.                                            |
| POST            | `/auth/logout`                                     | cookies            | Destroy session.                                                            |
| GET             | `/auth/me`                                         | session            | Current user + account.                                                     |
| GET/PATCH       | `/account`                                         | session            | The caller's account (no `/accounts/:id` by design).                        |
| CRUD            | `/competitors`, `/prompts`, `/verified-facts`      | session            | Tenant-scoped resources.                                                    |
| POST            | `/scans`                                           | session            | Creates scan row, enforces plan quota, runs the FULL pipeline; 202 + scanId. |
| GET             | `/scans`, `/scans/:id`                             | session            | Scan status/history (status + `stats.stages` = whole-pipeline progress).     |
| POST            | `/scans/:id/diagnose`, `/scans/:id/execute`        | session            | Re-run ONE stage without a full scan; quota-checked.                        |
| POST            | `/assets/:id/verify`                               | session            | Force the verification re-measure now (bypasses the scheduled delay).       |
| GET             | `/mentions`, `/gaps`, `/assets`, `/share-of-voice` | session            | Dashboard reads (pipeline writes them).                                     |
| GET             | `/assets/:id`                                      | session            | One asset + its generated content (read from `content_ref`, guarded).       |
| GET             | `/verifications`, `/verifications/:id`             | session            | Before/after proof: verdict, confidence, metrics.                           |
| POST/GET/DELETE | `/cms-credentials`                                 | session            | Envelope-encrypted; metadata-only responses.                                |
| GET             | `/billing`                                         | session            | Plan + limits (stub).                                                       |
| POST            | `/billing/checkout`, `/billing/webhook`            | —                  | 501 stubs; Stripe (with signature verification) lands with the frontend.    |
| GET             | `/internal/pipeline-health`                        | none (server-side) | Pings the pipeline via the shared-secret client.                            |

## Pipeline triggers

`POST /scans` inserts a `scans` row (status `pending`), then calls the Python
service's `POST /internal/scans/run` through the shared-secret
[PipelineClient](src/internal/pipeline-client.ts), which runs the **whole loop**
as a Celery chain: monitor → diagnose → plan+execute. The pipeline validates the
scan exists in the shared DB and acknowledges (202). If the pipeline is
unreachable the row stays `pending` and the API returns 502 with the `scanId`.

Poll `GET /scans/:id` for whole-pipeline progress: `status` covers the entire
chain (only `completed` once every stage ran; `failed` + `error` the moment one
does) and `stats.stages` carries each stage's result.

Individual stages can be re-run without a full scan —
`POST /scans/:id/diagnose`, `POST /scans/:id/execute`, `POST /assets/:id/verify`
([routes/stages.ts](src/routes/stages.ts)). Each is tenant-scoped (another
tenant's id 404s) and passes the same plan-quota gate as `POST /scans`, so a
re-run can't be used to walk around the cost cap.

**Verification is not chained** — a shipped fix needs time to land before
re-measuring is meaningful, so the pipeline's beat schedules it on a config delay
(`verification.yaml`). `POST /assets/:id/verify` forces it immediately.

## Config

All env vars are in [`.env.example`](.env.example) and validated by Zod in
[`src/config.ts`](src/config.ts) at boot. `INTERNAL_SHARED_SECRET` must match
the pipeline service. Secrets are never logged.
