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


@celery_app.task(name="verification.run_asset", bind=True, max_retries=0)
def run_verification_task(self, asset_id: str, account_id: str) -> dict[str, Any]:
    """Re-run a shipped asset's target prompts and record the before/after verdict."""
    from app.pipeline.verification.runner import run_verification

    return run_verification(account_id=account_id, asset_id=asset_id)


@celery_app.task(name="schedule.enqueue_due_scans")
def enqueue_due_scans_task() -> dict[str, Any]:
    """Beat entry point: create `scheduled` scans for due accounts (jittered,
    quota-checked) and enqueue each as a Monitor job."""
    from app.pipeline.schedule.runner import enqueue_due_scans

    return enqueue_due_scans(
        enqueue=lambda scan_id, account_id: run_scan_task.delay(scan_id, account_id)
    )
