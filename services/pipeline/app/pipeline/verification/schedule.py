# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Scheduling for the Verification stage.

Verification is deliberately NOT chained onto a scan: a shipped fix needs time to
be crawled and indexed before re-measuring the same prompts means anything. So
the beat sweeps for assets that shipped at least `schedule.delay_hours` ago and
haven't been verified yet, and enqueues one verification each.

`delay_hours: 0` makes assets due immediately — the switch for testing the loop
without waiting a week.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from app.db.base import SessionLocal
from app.db.repositories import AccountRepository, AssetRepository
from app.pipeline.verification.config import (
    VerificationConfig,
    get_verification_config,
)

EnqueueFn = Callable[[str, str], Any]  # (asset_id, account_id) -> anything


def enqueue_due_verifications(
    *,
    now: datetime | None = None,
    enqueue: EnqueueFn | None = None,
    cfg: VerificationConfig | None = None,
) -> dict[str, Any]:
    """Find shipped-and-due assets per account and hand each to `enqueue`.
    The callback is injectable so this is testable with no Celery broker."""
    now = now or datetime.now(UTC)
    cfg = cfg or get_verification_config()
    shipped_before = now - timedelta(hours=cfg.schedule.delay_hours)

    enqueued: list[tuple[str, str]] = []
    with SessionLocal() as session:
        assets_repo = AssetRepository(session)
        for account_id in AccountRepository(session).list_ids():
            for asset in assets_repo.list_due_for_verification(
                account_id, shipped_before
            ):
                enqueued.append((str(account_id), str(asset.id)))
                if enqueue is not None:
                    enqueue(str(asset.id), str(account_id))

    return {
        "due": len(enqueued),
        "enqueued": enqueued,
        "delay_hours": cfg.schedule.delay_hours,
    }
