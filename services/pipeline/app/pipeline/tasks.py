"""Celery tasks for pipeline stages.

Thin wrappers around the stage runners so orchestration (retry, routing) is
Celery's concern and the stage logic stays framework-free and unit-testable.
"""

from __future__ import annotations

from typing import Any

from app.celery_app import celery_app
from app.pipeline.monitor.runner import run_scan


@celery_app.task(name="monitor.run_scan", bind=True, max_retries=0)
def run_scan_task(self, scan_id: str, account_id: str) -> dict[str, Any]:
    """Run the Monitor stage for a scan and persist mentions + share_of_voice."""
    return run_scan(account_id=account_id, scan_id=scan_id)
