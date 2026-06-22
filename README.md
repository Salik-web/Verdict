# GEO SaaS

Generative Engine Optimization for B2B SaaS. Monitors whether AI engines (ChatGPT,
Perplexity, Gemini) recommend a company, diagnoses why not, fixes it on their site,
and proves which fixes moved citations.

**Pipeline loop:** Monitor → Diagnose → Plan → Execute → Verify.

## Architecture

Two services over one shared Postgres database. **The DB schema is the contract
between services** — change it only via migrations in [`/db`](db/).

| Path | Service | Stack |
| --- | --- | --- |
| [`apps/api`](apps/api/) | TypeScript API | Fastify, Drizzle, BullMQ+Redis, Zod |
| [`services/pipeline`](services/pipeline/) | Python ML pipeline | FastAPI + Celery + LangGraph, SQLAlchemy, Pydantic |
| [`packages/shared`](packages/shared/) | Cross-service contracts | TS types + JSON Schema |
| [`db`](db/) | Schema | SQL migrations (single source of truth) |
| [`infra`](infra/) | Local dev | docker-compose, env examples |

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

# 2. TypeScript API  (http://localhost:3000/health)
corepack enable
pnpm install
cp apps/api/.env.example apps/api/.env
pnpm --filter @geo/api dev

# 3. Python pipeline  (http://localhost:8000/health)
cd services/pipeline
cp .env.example .env
uv sync
uv run uvicorn app.main:app --reload
```

See each service's README for details:
[apps/api](apps/api/README.md) · [services/pipeline](services/pipeline/README.md) · [db](db/README.md).

## Checkpoint (Phase 1)

`docker compose up` brings up Postgres+pgvector+Redis; both services start; both
`/health` return 200; the TS API can reach the Python `/health` through the
authenticated internal client. No business logic yet.

## Conventions

- Secrets live in `.env` (gitignored). `.env.example` lists every var. Model API
  keys stay blank — the pipeline runs fully in **mock mode** without them (Phase 2).
- Everything typed and validated at boundaries: Zod/TS, Pydantic.
- Multi-tenant from day one: `account_id` on every row and every query.
- Secret scanning via [gitleaks](https://github.com/gitleaks/gitleaks)
  (`.gitleaks.toml`).
