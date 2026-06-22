# geo-pipeline — Python ML pipeline (FastAPI + Celery + LangGraph)

Does all AI work: measurement calls, parsing, diagnosis, content generation,
scraping, verification. FastAPI is a thin trigger layer; Celery workers run the
heavy stages as a LangGraph. SQLAlchemy over the shared Postgres. (Phase 1 ships
only health + the internal-secret guard — no business logic yet.)

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

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/health` | none | Liveness; returns the shared `HealthResponse` shape. |
| GET | `/internal/ping` | `x-internal-secret` | Authenticated liveness for internal callers (the TS API). |

## Config

All env vars are in [`.env.example`](.env.example), validated by
pydantic-settings in [`app/core/config.py`](app/core/config.py).
`INTERNAL_SHARED_SECRET` must match the API service. **Model API keys stay
blank** — `MOCK_MODE=true` runs the whole pipeline without them (Phase 2).
Settings are never logged.

## Internal auth

[`app/core/security.py`](app/core/security.py) exposes
`require_internal_secret`, a FastAPI dependency that requires the
`x-internal-secret` header (constant-time compared) on every `/internal/*`
route. Mirrors `INTERNAL_SECRET_HEADER` in `packages/shared`.
