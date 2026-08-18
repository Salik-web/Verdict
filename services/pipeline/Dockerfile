# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
#
# Python pipeline. Serves BOTH the FastAPI app and the Celery worker/beat — same
# image, different command (see infra/docker-compose.yml), so the worker can
# never drift from the API it shares code with.
#
#   docker build -f services/pipeline/Dockerfile services/pipeline

FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app

# uv, pinned — an unpinned installer is a silent build-reproducibility hole.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

# ── deps: locked, cached on the manifests alone ───────────────────────────────
FROM base AS deps
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# ── runtime ───────────────────────────────────────────────────────────────────
FROM deps AS runtime
COPY app ./app
COPY config ./config
COPY examples ./examples

# curl is here for the compose healthcheck; nothing in the app shells out.
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 pipeline \
    && chown -R pipeline:pipeline /app
USER pipeline

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
