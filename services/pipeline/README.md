# geo-pipeline — Python ML pipeline (FastAPI + Celery + LangGraph)

Does all AI work: measurement calls, parsing, diagnosis, content generation,
scraping, verification. FastAPI is a thin trigger layer; Celery workers run the
heavy stages as a LangGraph. SQLAlchemy over the shared Postgres. All model calls
go through the [model gateway](#model-gateway) (mock-first, no keys needed).

## Run

[uv](https://docs.astral.sh/uv/) manages the env and Python 3.12 (auto-fetched).

```bash
cd services/pipeline
cp .env.example .env
uv sync                                  # creates .venv, installs deps
uv run uvicorn app.main:app --reload     # http://localhost:8000
```

Celery worker (needs Redis from `infra/`):

```bash
uv run celery -A app.celery_app worker --loglevel=info
```

Tests / lint / format:

```bash
uv run pytest
uv run ruff check .
uv run black --check .
```

## Endpoints

| Method | Path                  | Auth                | Purpose                                                                                                                              |
| ------ | --------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| GET    | `/health`             | none                | Liveness; returns the shared `HealthResponse` shape.                                                                                 |
| GET    | `/internal/ping`      | `x-internal-secret` | Authenticated liveness for internal callers (the TS API).                                                                            |
| POST   | `/internal/scans/run` | `x-internal-secret` | Scan trigger from the TS API; validates the scan row exists in the shared DB, acknowledges with 202. Orchestration lands next phase. |

## Database

The shared Postgres schema lives in [`/db`](../../db/) (SQL is the source of
truth; see [SCHEMA.md](../../db/SCHEMA.md)). This service mirrors it in
SQLAlchemy ([app/db/models.py](app/db/models.py)) and accesses it only through
the tenant-scoped repository layer ([app/db/repositories/](app/db/repositories/))
— every query filters on `account_id`, no raw SQL in business logic.

Migrations/seed are run from the TS side (`pnpm --filter @geo/api db:migrate`);
this service reads the same DB. The repository integration test
([tests/test_repositories.py](tests/test_repositories.py)) reads the seeded demo
account and skips cleanly if the DB is unreachable.

## Model gateway

[`app/gateway/`](app/gateway/) is the single module that wraps **all** model
calls — everything downstream (measurement, processing, generation) goes through
it, never a provider SDK directly.

```python
from app.gateway import get_gateway, Message

gw = get_gateway()
res = gw.call(
    "measurement",
    [Message(role="user", content="Best product analytics tool for B2B SaaS?")],
    account_id=account_id,
    scenario="competitor_wins",   # mock-mode fixture selector (optional)
)
res.text, res.usage, res.cost_usd, res.model   # -> {text, usage, cost, model}
```

**Everything is config, not code.** [`config/models.yaml`](config/models.yaml)
maps each task to a provider+model per mode, and lists providers, pricing, rate
limits, retry, and cache settings. Changing a model — or a whole mode — is an
edit there, never a code change.

**Three modes** via `GATEWAY_MODE` (default `mock`):

| Mode   | Behavior                                                                              | Keys      |
| ------ | ------------------------------------------------------------------------------------- | --------- |
| `mock` | Canned, realistic responses from [`config/fixtures/`](config/fixtures/). **Default.** | none      |
| `dev`  | Free providers (Groq / OpenRouter / Ollama).                                          | free-tier |
| `prod` | Paid models (Perplexity Sonar, DeepSeek, Kimi).                                       | paid      |

Mock fixtures are **scenario-able** (`competitor_wins`, `customer_invisible`, …)
so they double as the test suite. Real (dev/prod) calls go through one
OpenAI-compatible HTTP adapter (covers Groq/OpenRouter/DeepSeek/Perplexity/Kimi);
the Gemini adapter lands with real keys.

Cross-cutting, handled in the gateway (not the providers): retries w/ backoff,
per-provider token-bucket rate limiting, in-memory response cache (swappable for
Redis), `call_batch()` (sequential now; async Batch API later), and **cost
tracking** — every call writes a row to `llm_cost_log` (the `mock` flag marks
simulated spend).

Checkpoint: `uv run pytest tests/test_gateway.py` — with no keys, a mock call per
task returns realistic text and logs a cost row; flipping a model is config-only.

## Monitor stage (visibility measurement)

The first pipeline stage — [`app/pipeline/monitor/`](app/pipeline/monitor/) —
measures whether AI engines recommend the account's brand. It's a LangGraph
(`measure_and_parse → compute_share_of_voice`) with typed Pydantic I/O
([`app/pipeline/contracts.py`](app/pipeline/contracts.py)), so it's swappable and
testable in isolation.

Flow, per scan:

1. **Prompt generation** ([prompts.py](app/pipeline/monitor/prompts.py)) — from a
   category, auto-generate ~25-30 high-intent buyer prompts via the gateway
   `generation` task. Templates live in
   [`config/prompts/`](config/prompts/), never inline.
2. **Measure** ([measure.py](app/pipeline/monitor/measure.py)) — ask each engine
   each active prompt `repeats` times (gateway `measurement` task).
3. **Parse** ([parse.py](app/pipeline/monitor/parse.py)) — LLM-as-judge (gateway
   `processing` task) extracts a typed `ParsedMention` (mentioned, position,
   sentiment, cited_urls, competitors). One focal-brand row → `mentions`.
4. **Share of voice** ([sov.py](app/pipeline/monitor/sov.py)) — aggregate across
   the repeats (never live) → `share_of_voice`. `mention_rate = mentions/obs`,
   `sov_pct = mentions / all-brand-mentions`, plus `avg_position`.

**Data-driven** ([config/monitor.yaml](config/monitor.yaml)): engines, `repeats`,
and prompt count. Starts with one engine; adding Perplexity Sonar / OpenAI /
Gemini is a new engine entry + a gateway task in
[models.yaml](config/models.yaml) — not a rewrite.

**Trigger:** the TS API calls `POST /internal/scans/run`, which enqueues the
`monitor.run_scan` Celery task
([app/pipeline/tasks.py](app/pipeline/tasks.py)). The runner
([runner.py](app/pipeline/monitor/runner.py)) drives the scan lifecycle
(`pending → running → completed/failed`) and persists via repositories.

Run a worker (needs Redis from `infra/`):

```bash
uv run celery -A app.celery_app worker --loglevel=info
```

Checkpoint (mock mode, no keys): `uv run pytest tests/test_monitor_stage.py
tests/test_scan_run.py` — the stage's SoV math is exact, and a scan for the demo
account writes 15 mentions + a share_of_voice roll-up.

## Config

All env vars are in [`.env.example`](.env.example), validated by
pydantic-settings in [`app/core/config.py`](app/core/config.py).
`INTERNAL_SHARED_SECRET` must match the API service. **Model API keys stay
blank** — `GATEWAY_MODE=mock` (the default) runs the whole pipeline without them.
Settings are never logged.

## Internal auth

[`app/core/security.py`](app/core/security.py) exposes
`require_internal_secret`, a FastAPI dependency that requires the
`x-internal-secret` header (constant-time compared) on every `/internal/*`
route. Mirrors `INTERNAL_SECRET_HEADER` in `packages/shared`.
