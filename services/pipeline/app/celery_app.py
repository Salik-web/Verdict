"""Celery application for pipeline workers.

Phase 1 wires the app to Redis but registers no real tasks. Stage tasks
(monitor/diagnose/execute/verify) get added in later phases. Run a worker with:

    uv run celery -A app.celery_app worker --loglevel=info
"""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

_settings = get_settings()

celery_app = Celery(
    "geo_pipeline",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
)


@celery_app.task(name="health.ping")
def ping() -> str:
    """Trivial task to verify the worker/broker wiring end-to-end."""
    return "pong"
