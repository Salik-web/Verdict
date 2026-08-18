# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Integration: an overdue account gets a jittered `scheduled` scan enqueued.

Uses a throwaway account with an old last-scan so it is unambiguously due, and an
injected enqueue callback (no Celery broker). Requires the migrated DB.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.db.base import SessionLocal
from app.db.models import Account, Scan
from app.pipeline.schedule.runner import enqueue_due_scans


def _db_ready() -> bool:
    try:
        with SessionLocal() as s:
            s.connection()
        return True
    except OperationalError:
        return False


def test_due_account_gets_scheduled_scan_enqueued():
    if not _db_ready():
        pytest.skip("database unreachable — run docker compose up + db:migrate")

    tag = uuid.uuid4().hex[:8]
    with SessionLocal() as s:
        account = Account(
            name=f"Sched Test {tag}",
            slug=f"sched-test-{tag}",
            brand_name="Sched Test",
            plan="enterprise",  # plenty of quota headroom
        )
        s.add(account)
        s.flush()
        account_id = account.id
        # Last scan well beyond one cadence ago -> due now, jitter notwithstanding.
        s.add(
            Scan(
                account_id=account_id,
                status="completed",
                engine_set=[],
                created_at=datetime.now(UTC) - timedelta(days=30),
            )
        )
        s.commit()

    try:
        calls: list[tuple[str, str]] = []
        summary = enqueue_due_scans(
            enqueue=lambda scan_id, acct_id: calls.append((scan_id, acct_id))
        )

        enqueued_accounts = {acct for acct, _ in summary["enqueued"]}
        assert str(account_id) in enqueued_accounts
        assert any(acct == str(account_id) for _, acct in calls)

        # A fresh `scheduled` scan now exists for this account (besides the old one).
        with SessionLocal() as s:
            scheduled = s.scalars(
                select(Scan).where(
                    Scan.account_id == account_id,
                    Scan.triggered_by == "scheduled",
                )
            ).all()
        assert len(scheduled) == 1
    finally:
        with SessionLocal() as s:
            acct = s.get(Account, account_id)
            if acct is not None:
                s.delete(acct)  # cascades to its scans
                s.commit()
