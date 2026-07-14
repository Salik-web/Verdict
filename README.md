# GEO SaaS

Generative Engine Optimization for B2B SaaS. Monitors whether AI engines (ChatGPT,
Perplexity, Gemini) recommend a company, diagnoses why not, fixes it on their site,
and proves which fixes moved citations.

**Pipeline loop:** Monitor → Diagnose → Plan → Execute → Verify.

## Architecture

Two services over one shared Postgres database. **The DB schema is the contract
between services** — change it only via migrations in [`/db`](db/).

| Path                                      | Service                 | Stack                                              |
| ----------------------------------------- | ----------------------- | -------------------------------------------------- |
| [`apps/api`](apps/api/)                   | TypeScript API          | Fastify, Drizzle, BullMQ+Redis, Zod                |
| [`services/pipeline`](services/pipeline/) | Python ML pipeline      | FastAPI + Celery + LangGraph, SQLAlchemy, Pydantic |
| [`packages/shared`](packages/shared/)     | Cross-service contracts | TS types + JSON Schema                             |
| [`db`](db/)                               | Schema                  | SQL migrations (single source of truth)            |
| [`infra`](infra/)                         | Local dev               | docker-compose, env examples                       |

**Communication:** (1) shared Postgres (the spine), (2) internal HTTP — the TS API
calls the Python service's trigger endpoints, authenticated with a shared secret.
There is **no** cross-language shared queue.

## Quick start (local)

Prereqs: Docker + Docker Compose, Node 20+ with [corepack](https://nodejs.org/api/corepack.html),
and [uv](https://docs.astral.sh/uv/).

```bash
# 1. Infra: Postgres 16 (+pgvector) and Redis
cd infra
cp .env.example .env
docker compose up -d

# 2. Schema: apply migrations + seed the demo account
#    (the SQL in /db is the source of truth; see db/SCHEMA.md)
cd ..
corepack enable
pnpm install
cp apps/api/.env.example apps/api/.env
pnpm --filter @geo/api db:migrate
pnpm --filter @geo/api db:seed

# 3. TypeScript API  (http://localhost:3000/health)
pnpm --filter @geo/api dev

# 4. Python pipeline  (http://localhost:8000/health)
cd services/pipeline
cp .env.example .env
uv sync
uv run uvicorn app.main:app --reload
```

**Mock-first:** the entire pipeline runs end-to-end with **no API keys**
(`GATEWAY_MODE=mock`, the default) — realistic canned responses from fixtures.
Real keys are a one-line config switch at the end.

See each service's README for details:
[apps/api](apps/api/README.md) · [services/pipeline](services/pipeline/README.md) · [db](db/README.md) · [schema contract](db/SCHEMA.md).

## The pipeline (services/pipeline)

All AI work runs as swappable, independently testable LangGraph stages, each with
typed Pydantic I/O. Every model call goes through the **model gateway** — mode
(`mock`/`dev`/`prod`) and task→model mapping live in config, not code. See the
[pipeline README](services/pipeline/README.md) for detail.

| Stage              | What it does                                                                                                                                                                                    |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Model gateway**  | One entry point for every model call; mock mode (no keys), retries, caching, rate limiting, per-call cost logging.                                                                              |
| **Monitor**        | Ask AI engines the account's prompts N times, parse each answer (LLM-as-judge) → `mentions`, compute smoothed **share of voice**.                                                               |
| **Diagnose**       | SSRF-guarded scrape of the site; SEO + GEO checks, robots.txt **AI-bot audit** (blocked-search-bot + trap detection), llms.txt → typed `gaps`.                                                  |
| **Plan + Execute** | Rank gaps (impact×control×confidence), generate the top fix (comparison page / robots.txt / llms.txt) using **verified facts only**, sanitize + validate, store a tagged, downloadable `asset`. |
| **Verify**         | Re-run a shipped asset's exact prompts (reusing Monitor), compare before/after share of voice → an honest `verifications` verdict + confidence; feed it back into the planner. Jittered scheduling + plan-quota double-check. |

## Build progress

Each phase is built, tested on one real example, and reviewed before the next.

- **1 — Foundations:** monorepo, docker infra (Postgres+pgvector, Redis), health
  checks, internal shared-secret auth between services.
- **2 — Schema:** the full multi-tenant schema as SQL migrations (the contract),
  mirrored in Drizzle + SQLAlchemy; repository layers; seed.
- **3 — Model gateway:** provider abstraction, mock/dev/prod modes, fixtures,
  cost tracking.
- **4 — App layer:** local auth (argon2 + httpOnly sessions w/ refresh rotation),
  tenant isolation (no IDOR), Zod validation, Redis rate limits + plan quotas,
  security headers/CORS, CRUD + dashboard reads, `POST /scans` pipeline trigger,
  envelope-encrypted CMS credentials.
- **5 — Monitor:** visibility measurement + share of voice.
- **6 — Diagnose:** SEO/GEO audit, AI-bot robots audit, SSRF-guarded scraper.
- **7 — Plan + Execute:** gap ranking + the comparison-page/robots/llms
  generators with verified-facts enforcement and HTML sanitization.
- **8 — Verify:** verification stage (before/after proof reusing Monitor, honest
  verdict + confidence feeding back into the planner), jittered scheduling, and a
  plan-quota double-check.
- **9 — Hardening:** security sweep + [SECURITY.md](SECURITY.md) checklist,
  [SCALING.md](SCALING.md), structured logging + optional Sentry (scrubbed),
  `/internal/costs`, CI (gitleaks + `pnpm audit` + `pip-audit`) + Dependabot, and
  a full-loop end-to-end test with all guards active.

Checkpoints run in mock mode (no keys): `pnpm --filter @geo/api test` (TS) and
`cd services/pipeline && uv run pytest` (pipeline).

## Conventions

- Secrets live in `.env` (gitignored). `.env.example` lists every var. Model API
  keys stay blank — the pipeline runs fully in **mock mode** without them, via the
  model gateway.
- Everything typed and validated at boundaries: Zod/TS, Pydantic.
- Multi-tenant from day one: `account_id` on every row and every query.
- Secret scanning via [gitleaks](https://github.com/gitleaks/gitleaks)
  (`.gitleaks.toml`).
