"""Scheduler runner: find accounts whose next scan is due and enqueue them.

`select_due_accounts` is the decision (reads the DB, applies the jittered cadence);
`enqueue_due_scans` is the action (quota-checks, creates a `scheduled` scan row,
and hands each off to an injectable enqueue callback). Keeping the callback
injectable means the whole flow is testable with no Celery broker.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.db.repositories import AccountRepository, ScanRepository
from app.pipeline.quota import QuotaExceeded, check_quota
from app.pipeline.schedule.config import ScheduleConfig, get_schedule_config
from app.pipeline.schedule.jitter import is_due

EnqueueFn = Callable[[str, str], Any]  # (scan_id, account_id) -> anything


def select_due_accounts(
    session: Session,
    now: datetime,
    cfg: ScheduleConfig | None = None,
) -> list[uuid.UUID]:
    cfg = cfg or get_schedule_config()
    scans = ScanRepository(session)
    due: list[uuid.UUID] = []
    for account_id in AccountRepository(session).list_ids():
        last = scans.last_created_at(account_id)
        if is_due(account_id, last, now, cfg):
            due.append(account_id)
    return due


def enqueue_due_scans(
    *,
    now: datetime | None = None,
    enqueue: EnqueueFn | None = None,
    cfg: ScheduleConfig | None = None,
) -> dict[str, Any]:
    """Create `scheduled` scans for every due account (subject to quota) and hand
    each to `enqueue`. Returns a summary for the caller/task to log."""
    now = now or datetime.now(UTC)
    cfg = cfg or get_schedule_config()

    enqueued: list[tuple[str, str]] = []
    skipped_quota: list[str] = []

    with SessionLocal() as session:
        due = select_due_accounts(session, now, cfg)
        accounts = AccountRepository(session)
        scans = ScanRepository(session)
        for account_id in due:
            account = accounts.get_by_id(account_id)
            plan = account.plan if account is not None else None
            try:
                check_quota(session, account_id, plan=plan, now=now)
            except QuotaExceeded:
                skipped_quota.append(str(account_id))
                continue
            scan = scans.create(account_id, triggered_by="scheduled")
            session.commit()
            enqueued.append((str(account_id), str(scan.id)))
            if enqueue is not None:
                enqueue(str(scan.id), str(account_id))

    return {
        "due": len(due),
        "enqueued": enqueued,
        "skipped_quota": skipped_quota,
    }
