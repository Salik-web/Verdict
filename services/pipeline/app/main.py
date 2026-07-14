"""FastAPI app for the pipeline service.

Thin HTTP layer: a public /health and authenticated /internal/* trigger
endpoints. The heavy AI work runs in Celery workers (see app.celery_app) — the
HTTP layer only validates, enqueues, and reports.
"""

from __future__ import annotations

from fastapi import FastAPI

from app import __version__
from app.api import health, internal
from app.core.observability import configure_logging, init_sentry

configure_logging()
init_sentry()  # no-op unless SENTRY_DSN is set

app = FastAPI(title="GEO Pipeline", version=__version__)

app.include_router(health.router)
app.include_router(internal.router)
