# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Celery tasks for pipeline stages, and the chain that runs the loop.

Thin wrappers around the stage runners so orchestration (retry, routing, chaining)
is Celery's concern and the stage logic stays framework-free and unit-testable.

The full pipeline is a Celery **chain**:

    monitor -> diagnose -> plan+execute -> finalize

One scan trigger runs all of it. Each stage records its own `jobs` row
(queued -> running -> succeeded/failed) and merges its result into
`scans.stats["stages"]`, so polling a scan shows real progress. A stage that
raises marks the job AND the scan failed and re-raises, which aborts the chain —
downstream stages don't run, rather than the loop silently stopping half-done.

Verification is NOT chained: a fix needs time to land before re-measuring means
anything, so the beat schedules it separately (see verification/schedule.py).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from celery import chain

from app.celery_app import celery_app
from app.db.base import SessionLocal
from app.db.repositories import AccountRepository, JobRepository, ScanRepository
from app.pipeline.diagnosis.runner import run_diagnosis
from app.pipeline.execution.runner import load_open_gaps, run_execution
from app.pipeline.monitor.runner import run_scan


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)


def _stage(
    name: str,
    account_id: uuid.UUID | str,
    scan_id: uuid.UUID | str,
    fn: Callable[[], dict[str, Any]],
    *,
    external_id: str | None = None,
) -> dict[str, Any]:
    """Run one stage with jobs-row bookkeeping + scan progress.

    On failure: the job and the scan are both marked failed with the error, and
    the exception is re-raised so the Celery chain aborts cleanly.
    """
    account_id = _as_uuid(account_id)
    scan_id = _as_uuid(scan_id)

    with SessionLocal() as session:
        jobs = JobRepository(session)
        job = jobs.create(
            account_id=account_id,
            scan_id=scan_id,
            type=name,
            external_id=external_id,
        )
        job_id = job.id
        jobs.mark_running(job_id)
        session.commit()

    try:
        result = fn()
    except Exception as exc:
        with SessionLocal() as session:
            JobRepository(session).mark_failed(job_id, str(exc))
            ScanRepository(session).mark_failed(account_id, scan_id, f"{name}: {exc}")
            session.commit()
        raise

    with SessionLocal() as session:
        JobRepository(session).mark_succeeded(job_id, result)
        ScanRepository(session).record_stage(account_id, scan_id, name, result)
        session.commit()
    return result


# ── Stage tasks ──────────────────────────────────────────────────────────
@celery_app.task(name="monitor.run_scan", bind=True, max_retries=0)
def run_scan_task(
    self, scan_id: str, account_id: str, finalize: bool = True
) -> dict[str, Any]:
    """Monitor stage. `finalize=False` when chained (the chain completes the scan
    once every stage has run); True when run standalone."""
    if finalize:
        return run_scan(account_id=account_id, scan_id=scan_id)
    return _stage(
        "monitor",
        account_id,
        scan_id,
        lambda: run_scan(account_id=account_id, scan_id=scan_id, finalize=False),
        external_id=self.request.id,
    )


@celery_app.task(name="diagnosis.run", bind=True, max_retries=0)
def run_diagnosis_task(self, scan_id: str, account_id: str) -> dict[str, Any]:
    """Diagnosis stage: audit the account's site -> typed gaps for this scan."""

    def _run() -> dict[str, Any]:
        # Nothing to scrape without a domain — a skip, not a pipeline failure.
        with SessionLocal() as session:
            account = AccountRepository(session).get_by_id(_as_uuid(account_id))
            if account is None or not account.domain:
                return {"skipped": True, "reason": "account has no domain to diagnose"}
        return run_diagnosis(account_id, scan_id=scan_id)

    return _stage("diagnosis", account_id, scan_id, _run, external_id=self.request.id)


@celery_app.task(name="execution.run", bind=True, max_retries=0)
def run_execution_task(self, scan_id: str, account_id: str) -> dict[str, Any]:
    """Plan + Execute stage: rank the gaps and ship the single top fix."""

    def _run() -> dict[str, Any]:
        # No gaps is a legitimate outcome (clean site), not a failure.
        with SessionLocal() as session:
            gaps = load_open_gaps(session, _as_uuid(account_id), _as_uuid(scan_id))
        if not gaps:
            return {"skipped": True, "reason": "no open gaps to execute"}
        return run_execution(account_id, scan_id=scan_id)

    return _stage("execution", account_id, scan_id, _run, external_id=self.request.id)


@celery_app.task(name="pipeline.finalize_scan")
def finalize_scan_task(scan_id: str, account_id: str) -> dict[str, Any]:
    """Last link in the chain: every stage ran, so the scan is complete. Keeps the
    per-stage stats the stages recorded."""
    with SessionLocal() as session:
        repo = ScanRepository(session)
        scan = repo.get(account_id, scan_id)
        stats = dict(scan.stats or {}) if scan is not None else {}
        stats["pipeline"] = "monitor -> diagnosis -> execution"
        repo.mark_completed(account_id, scan_id, stats)
        session.commit()
    return {"scan_id": str(scan_id), "status": "completed"}


@celery_app.task(name="verification.run_asset", bind=True, max_retries=0)
def run_verification_task(self, asset_id: str, account_id: str) -> dict[str, Any]:
    """Re-run a shipped asset's target prompts and record the before/after verdict."""
    from app.pipeline.verification.runner import run_verification

    return run_verification(account_id=account_id, asset_id=asset_id)


# ── Beat tasks ───────────────────────────────────────────────────────────
@celery_app.task(name="schedule.enqueue_due_scans")
def enqueue_due_scans_task() -> dict[str, Any]:
    """Beat entry point: create `scheduled` scans for due accounts (jittered,
    quota-checked) and run the full pipeline for each."""
    from app.pipeline.schedule.runner import enqueue_due_scans

    return enqueue_due_scans(
        enqueue=lambda scan_id, account_id: start_pipeline(scan_id, account_id)
    )


@celery_app.task(name="schedule.sweep_stale_scans")
def sweep_stale_scans_task() -> dict[str, Any]:
    """Beat entry point: fail scans whose worker died.

    The soft time limit only fires inside a task that is still alive; a process
    that was killed leaves its scan at `running` forever. This is the backstop.
    """
    from app.pipeline.schedule.sweeper import sweep_stale_scans

    return sweep_stale_scans()


@celery_app.task(name="verification.enqueue_due")
def enqueue_due_verifications_task() -> dict[str, Any]:
    """Beat entry point: verify assets that shipped at least `delay_hours` ago."""
    from app.pipeline.verification.schedule import enqueue_due_verifications

    return enqueue_due_verifications(
        enqueue=lambda asset_id, account_id: run_verification_task.delay(
            asset_id, account_id
        )
    )


# ── The chain ────────────────────────────────────────────────────────────
def start_pipeline(scan_id: uuid.UUID | str, account_id: uuid.UUID | str) -> str:
    """Kick off monitor -> diagnose -> plan+execute -> finalize for one scan.

    Immutable signatures (`si`) so each stage gets explicit args rather than the
    previous stage's return value. Returns the chain's task id.
    """
    sig = chain(
        run_scan_task.si(str(scan_id), str(account_id), False),
        run_diagnosis_task.si(str(scan_id), str(account_id)),
        run_execution_task.si(str(scan_id), str(account_id)),
        finalize_scan_task.si(str(scan_id), str(account_id)),
    )
    return sig.apply_async().id
