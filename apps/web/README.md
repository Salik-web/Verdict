# apps/web — throwaway backend test harness

**This is not the product UI.** It's a deliberately ugly, functional-only
click-through harness to prove the GEO backend V1 works end-to-end against the
real API (which runs in `GATEWAY_MODE=mock`, so the data is mock but travels the
real path: API → DB → screen). It will be thrown away and replaced by the real
designed frontend.

Next.js (App Router) + TypeScript + Tailwind (default utilities only). No
component/chart/state libraries. Every screen calls the real TS API with session
cookies and prints status + body on any error.

## Run it

Three processes. From the repo root:

```bash
# 1. Infra (Postgres + Redis) — if not already up
cd infra && docker compose up -d && cd ..

# 2. TS API on :3000 (its FRONTEND_ORIGIN must be this app's origin, :5173 —
#    that's the default in apps/api/.env.example, so nothing to change)
pnpm --filter @geo/api db:migrate && pnpm --filter @geo/api db:seed
pnpm --filter @geo/api dev

# 3. Python pipeline on :8000 (FastAPI accepts the scan trigger)
cd services/pipeline && uv run uvicorn app.main:app --port 8000

# 4. Celery WORKER — REQUIRED, or scans sit at "pending" forever (the trigger
#    just enqueues; the worker runs the chain). On Windows use --pool=solo.
cd services/pipeline && uv run celery -A app.celery_app worker --pool=solo --loglevel=info

# 5. Celery BEAT — optional. Only needed for *scheduled* work: periodic scans and
#    the verification re-measure. You can skip it and force verification with
#    POST /assets/:id/verify instead.
cd services/pipeline && uv run celery -A app.celery_app beat --loglevel=info

# 6. This harness on :5173
pnpm --filter @geo/web dev
```

Then open http://localhost:5173.

> **Self row is bold only when your brand matches a mock brand.** The mock engine
> always answers about a fixed set (Acme Analytics, Globex Insights, Initech
> Metrics, Mixpanel, Amplitude). Share-of-voice marks `isSelf` by matching your
> account **brand name** (or a competitor flagged `isSelf`). So on **/setup**, set
> the brand name to e.g. `Acme Analytics` before scanning to see the self row
> light up — otherwise every row is `isSelf: false` (correct, just not self).

### Env

Copy `.env.example` to `.env.local`:

- `NEXT_PUBLIC_API_BASE_URL` — the TS API base URL (default `http://localhost:3000`).
  The browser calls it directly with credentials, so the API's `FRONTEND_ORIGIN`
  **must** equal this app's origin (`http://localhost:5173`).
- `PIPELINE_INTERNAL_URL` + `INTERNAL_SHARED_SECRET` — server-side only, used by
  the `/costs` proxy route (screen 8) to reach the shared-secret-guarded cost
  endpoint on the Python pipeline. Must match the pipeline's secret.

## Click-through order (the full loop)

**Fastest path — log in as the pre-populated demo account:**
`owner@acme.example.com`, with the password `pnpm --filter @geo/api db:seed`
printed when you ran it (generated fresh each time, never committed). Its brand
is `Acme Analytics`, which matches the mock engine's answers, so the self row
lights up.

1. **/login** — log in as the demo account above (or sign up: password ≥ 10 chars).
2. **/setup** — competitors/prompts/facts are already seeded for the demo account.
   (A fresh signup starts empty — see finding 1.) Hit **Run scan**.
3. **/scans** — click **poll**. One scan runs the whole chain
   (monitor → diagnose → plan+execute); `stats.stages` shows per-stage progress
   until it reaches `completed`.
4. **/dashboard** — share-of-voice leaderboard; SoV sums to ~100%, self row bold.
5. **/gaps** — the ranked gaps diagnosis just produced.
6. **/assets** — the generated comparison page; **view content** renders it.
7. **/proof** — verification verdicts. Verification is *scheduled*, not chained
   (a fix needs time to land), so either set `schedule.delay_hours: 0` in
   `services/pipeline/config/verification.yaml` and let the beat pick it up, or
   force it now with `POST /assets/:id/verify`.
8. **/costs** — the cost roll-up; confirm `real_calls: 0` (100% mock).

## Findings (backend gaps this harness surfaced)

Reported, not worked around. 2–5 have since been fixed on the backend; 1 remains.

1. **No prompt auto-generation.** Signup seeds nothing and there's no
   generate-prompts endpoint, so a **fresh** account starts with zero prompts; add
   them manually on **/setup** (a scan needs ≥ 1 active prompt). The demo account
   is seeded, so this only bites on new signups.
2. ~~Only the Monitor scan is triggerable~~ — **fixed.** `POST /scans` now runs the
   whole Celery chain (monitor → diagnose → plan+execute), the scan's status +
   `stats.stages` reflect the whole pipeline, and per-stage triggers exist
   (`POST /scans/:id/diagnose`, `POST /scans/:id/execute`,
   `POST /assets/:id/verify`). Verification is scheduled on a config delay rather
   than chained.
3. ~~No `GET /verifications`~~ — **added** (+ `/verifications/:id`), tenant-scoped,
   cross-tenant → 404. Powers /proof.
4. ~~No asset-content endpoint~~ — **added** (`GET /assets/:id`) returning the row
   plus its sanitized HTML read from `content_ref` (path-traversal + cross-tenant
   guarded in `apps/api/src/artifacts.ts`); /assets renders it in a locked-down
   `sandbox=""` iframe.
5. ~~Demo account has no password~~ — **fixed**, it's seeded now (above).
6. **Self row needs a brand-name match.** SoV marks `isSelf` by matching your
   account brand name (or a competitor flagged `isSelf`) against the fixed mock
   brands — the demo account already matches; a fresh signup should set brand name
   to e.g. `Acme Analytics` on /setup.
7. **`/internal/costs` is on the Python pipeline** and shared-secret guarded, so
   /costs goes through the Next server route `app/api/costs/route.ts` (expected).
