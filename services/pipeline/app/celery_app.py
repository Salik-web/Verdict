"""Celery application for pipeline workers.

Run a worker with:

    uv run celery -A app.celery_app worker --loglevel=info

Stage tasks live in app.pipeline.tasks (imported via `include` below) so the
worker discovers them without creating an import cycle at module load.
"""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings
from app.pipeline.schedule.config import get_schedule_config

_settings = get_settings()

celery_app = Celery(
    "geo_pipeline",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
    include=["app.pipeline.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
)

# Config-driven beat: tick every `tick_minutes` and enqueue whatever is due. Run
# the beat alongside a worker:  uv run celery -A app.celery_app beat
celery_app.conf.beat_schedule = {
    "enqueue-due-scans": {
        "task": "schedule.enqueue_due_scans",
        "schedule": float(get_schedule_config().tick_minutes * 60),
    },
}


@celery_app.task(name="health.ping")
def ping() -> str:
    """Trivial task to verify the worker/broker wiring end-to-end."""
    return "pong"
