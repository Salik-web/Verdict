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

## Diagnosis stage (why the customer loses)

[`app/pipeline/diagnosis/`](app/pipeline/diagnosis/) — a LangGraph
(`fetch_home → run_checks → map_gaps`) that audits a site's SEO + GEO health and
emits typed `Gap` rows. Pure w.r.t. the DB; the network is reached only through
an injected `Fetcher`, and LLM calls go through the gateway (mock by default).

- **SSRF guard** ([ssrf.py](app/pipeline/diagnosis/ssrf.py)) — every fetch (and
  every redirect hop) must pass `assert_public_url`: only http/https to
  globally-routable IPs. Private ranges, loopback, link-local, the
  `169.254.169.254` metadata endpoint, and CGNAT are rejected. Scraped content is
  untrusted **data**, never fed to a model as instructions.
- **Fetcher** ([fetcher.py](app/pipeline/diagnosis/fetcher.py)) — `HttpxFetcher`
  with caps (timeout, max redirects, size), a polite UA, and rate limiting. A
  `PlaywrightFetcher` (JS render) can drop in behind the same interface.
- **Crawler / robots audit** ([robots_audit.py](app/pipeline/diagnosis/robots_audit.py))
  — classifies every AI bot via [config/ai_bots.yaml](config/ai_bots.yaml) into
  **TRAINING** vs **SEARCH**. A blocked SEARCH bot is **urgent**; the named trap
  (GPTBot allowed while OAI-SearchBot blocked) is flagged. Bot list is config.
- **llms.txt** ([llms_txt.py](app/pipeline/diagnosis/llms_txt.py)) — flag if
  missing/stale.
- **SEO** ([seo.py](app/pipeline/diagnosis/seo.py)) — schema, headings,
  indexability, freshness, page-weight (deterministic).
- **GEO** ([geo.py](app/pipeline/diagnosis/geo.py)) — owned comparison page,
  presence in cited third-party sources, and an LLM-as-judge quotability /
  entity-consistency assessment via the gateway.

Every failing finding maps through
[config/gap_taxonomy.yaml](config/gap_taxonomy.yaml) to a `Gap` with a `fix_type`
(consumed by the Execute stage) and a rank score. Gaps persist to the `gaps`
table (`fix_type`/layer/severity in `details` jsonb — no schema change).

Checkpoint (no keys): `uv run pytest tests/test_ssrf.py tests/test_bot_audit.py
tests/test_diagnosis_stage.py`. Live scrape of example.com is opt-in:
`RUN_LIVE_SCRAPE=1 uv run pytest tests/test_diagnosis_live.py`.

## Execution stage (plan the gaps, ship one fix)

[`app/pipeline/execution/`](app/pipeline/execution/) — rank the gaps, then
generate + validate the single highest-value fix.

- **Planner** ([planner.py](app/pipeline/execution/planner.py)) — scores each gap
  `impact × control × confidence` (config-weighted,
  [config/planner.yaml](config/planner.yaml)) and dedups by `fix_type` (one asset
  can resolve several queries), emitting a ranked backlog.
- **Generator interface** ([base.py](app/pipeline/execution/base.py)) —
  `generate(item, context) -> AssetDraft`. New fix types register in
  [registry.py](app/pipeline/execution/registry.py) with no stage change.
- **ComparisonPageGenerator** — gap + competitor + `verified_facts` → structured
  HTML + FAQ JSON-LD via the gateway `generation` task. **Every customer-specific
  claim must come from `verified_facts`.** Plus small **robots.txt fixer** and
  **llms.txt generator** sharing the same interface.
- **Validation** ([validate.py](app/pipeline/execution/validate.py)) — rejects
  any `self` claim not backed by an active verified fact (hallucinated pricing →
  `rejected`), and sanitizes HTML with **nh3** (scripts/dangerous attrs stripped,
  XSS defense) before an asset is deliverable.
- **Delivery** — asset content is written to a downloadable file
  (`content_ref`) under `artifacts/` (gitignored); the `assets` row is tagged
  with `target_prompt_ids` for later verification. `fix_type`/claims/violations
  live in `metadata` jsonb (no schema change).

Checkpoint (no keys): `uv run pytest tests/test_planner.py
tests/test_execution_stage.py` — a `no_owned_comparison_page` gap yields a valid
comparison page from verified facts only; injected fake pricing is rejected; the
asset is tagged to its queries. `verified_facts` for the demo account are in the
seed.

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
