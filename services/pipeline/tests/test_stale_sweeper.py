# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Stale-scan sweeper (A2).

The gap it closes: Celery's soft time limit raises INSIDE a live task, so the
stage wrapper marks the scan failed. A worker that stops existing — OOM kill,
container eviction, the hard time limit — runs no handler at all, and its scan
sits at `running` forever. To a user that is indistinguishable from a slow scan,
because scans legitimately take minutes.

What must hold:
  * an over-deadline pending OR running scan is failed, with a reason that says
    why rather than "unknown error";
  * a scan inside the deadline is left completely alone (sweeping too eagerly
    kills legitimate slow scans — on a free tier, slow is normal);
  * a finished scan is never touched, whatever its age.

Requires the migrated DB; skips cleanly if unreachable.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import OperationalError

from app.db.base import SessionLocal
from app.db.models import Account, Scan
from app.db.repositories import ScanRepository
from app.pipeline.schedule.config import get_schedule_config
from app.pipeline.schedule.sweeper import sweep_stale_scans


def _db_ready() -> bool:
    try:
        with SessionLocal() as s:
            s.connection()
        return True
    except OperationalError:
        return False


@pytest.fixture
def account():
    if not _db_ready():
        pytest.skip("database unreachable — run docker compose up + db:migrate")
    with SessionLocal() as s:
        acc = Account(name="Sweeper Test", slug=f"sweeper-{uuid.uuid4().hex[:10]}")
        s.add(acc)
        s.commit()
        acc_id = acc.id
    yield acc_id
    with SessionLocal() as s:
        s.query(Account).filter(Account.id == acc_id).delete()
        s.commit()


def _scan(account_id, status: str, age_minutes: int, *, started: bool = True):
    """Insert a scan aged `age_minutes` into the past."""
    when = datetime.now(UTC) - timedelta(minutes=age_minutes)
    with SessionLocal() as s:
        scan = Scan(
            account_id=account_id,
            status=status,
            engine_set=[],
            started_at=when if started else None,
        )
        s.add(scan)
        s.flush()
        # created_at has a server default, so age it explicitly — a pending scan
        # that never started is swept on created_at.
        scan.created_at = when
        s.commit()
        return scan.id


def _status(account_id, scan_id) -> tuple[str, str | None]:
    with SessionLocal() as s:
        row = ScanRepository(s).get(account_id, scan_id)
        return row.status, row.error


def test_sweeps_a_running_scan_whose_worker_died(account):
    stale = get_schedule_config().stale_after_minutes
    scan_id = _scan(account, "running", stale + 5)

    result = sweep_stale_scans()

    assert result["swept"] >= 1
    assert str(scan_id) in [s["scan_id"] for s in result["scans"]]

    status, error = _status(account, scan_id)
    assert status == "failed"
    # The reason has to explain itself — an operator reading this row later
    # should not have to guess why the scan died.
    assert "worker" in error.lower()
    assert str(stale) in error


def test_sweeps_a_pending_scan_that_never_started(account):
    """A scan that died BEFORE mark_running() has started_at NULL. Falling back
    to created_at is what stops it being invisible to the sweep forever."""
    stale = get_schedule_config().stale_after_minutes
    scan_id = _scan(account, "pending", stale + 5, started=False)

    sweep_stale_scans()

    status, _ = _status(account, scan_id)
    assert status == "failed"


def test_leaves_a_scan_inside_the_deadline_alone(account):
    """Free-tier scans are slow by design. Sweeping eagerly would kill working
    scans, which is worse than the bug being fixed."""
    stale = get_schedule_config().stale_after_minutes
    scan_id = _scan(account, "running", max(stale - 5, 1))

    result = sweep_stale_scans()

    assert str(scan_id) not in [s["scan_id"] for s in result["scans"]]
    status, _ = _status(account, scan_id)
    assert status == "running"


@pytest.mark.parametrize("terminal", ["completed", "failed"])
def test_never_touches_a_finished_scan(account, terminal):
    scan_id = _scan(account, terminal, 60 * 24 * 30)  # a month old

    sweep_stale_scans()

    status, _ = _status(account, scan_id)
    assert status == terminal


def test_sweep_is_idempotent(account):
    stale = get_schedule_config().stale_after_minutes
    _scan(account, "running", stale + 5)

    first = sweep_stale_scans()
    second = sweep_stale_scans()

    assert first["swept"] >= 1
    # Already failed, so no longer a candidate — the beat runs every few minutes
    # and must not re-report the same scans forever.
    assert second["swept"] == 0


def test_deadline_stays_above_the_hard_task_limit():
    """A config guard, not a behaviour test: if the sweep deadline ever drops
    below the hard kill, the sweeper starts racing tasks that are still alive."""
    from app.core.config import get_settings

    hard_limit_minutes = get_settings().celery_task_time_limit_s / 60
    assert get_schedule_config().stale_after_minutes > hard_limit_minutes
