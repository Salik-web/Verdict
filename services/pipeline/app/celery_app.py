"""Celery application for pipeline workers.

Run a worker with:

    uv run celery -A app.celery_app worker --loglevel=info

Stage tasks live in app.pipeline.tasks (imported via `include` below) so the
worker discovers them without creating an import cycle at module load.
"""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings
from app.core.observability import configure_logging, init_sentry
from app.pipeline.schedule.config import get_schedule_config
from app.pipeline.verification.config import get_verification_config

configure_logging()
init_sentry()  # no-op unless SENTRY_DSN is set

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
    # A real (non-mock) stage can hang on a slow/rate-limited provider. The SOFT
    # limit raises SoftTimeLimitExceeded *inside* the task, so `_stage`'s except
    # block still runs and marks the job + scan failed with the error — no scan
    # left stuck at `running`. The HARD limit is the backstop that kills a truly
    # wedged process; it's higher so the soft path wins in practice.
    task_soft_time_limit=_settings.celery_task_soft_time_limit_s,
    task_time_limit=_settings.celery_task_time_limit_s,
)

# Config-driven beat: tick every `tick_minutes` and enqueue whatever is due. Run
# the beat alongside a worker:  uv run celery -A app.celery_app beat
celery_app.conf.beat_schedule = {
    "enqueue-due-scans": {
        "task": "schedule.enqueue_due_scans",
        "schedule": float(get_schedule_config().tick_minutes * 60),
    },
    # Verification is scheduled, never chained: a shipped fix needs time to land
    # before re-measuring. Delay + tick are config (verification.yaml).
    "enqueue-due-verifications": {
        "task": "verification.enqueue_due",
        "schedule": float(get_verification_config().schedule.check_every_minutes * 60),
    },
}


@celery_app.task(name="health.ping")
def ping() -> str:
    """Trivial task to verify the worker/broker wiring end-to-end."""
    return "pong"
