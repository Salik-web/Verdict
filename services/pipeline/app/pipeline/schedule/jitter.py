# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Pure scheduling math: when is an account's next scan due, and is it due now?

The jitter offset is a *deterministic* function of the account id (stable hash),
so every account keeps its own slot in the cadence window across restarts — the
cohort spreads out instead of thundering in together, with no random state to
persist. No DB, no clock reads except the `now` you pass in — fully testable.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta

from app.pipeline.schedule.config import ScheduleConfig


def jitter_offset_seconds(account_id: uuid.UUID | str, window_seconds: int) -> int:
    """Stable offset in [0, window_seconds) derived from the account id."""
    if window_seconds <= 0:
        return 0
    digest = hashlib.sha256(str(account_id).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % window_seconds


def next_run_at(
    account_id: uuid.UUID | str,
    last_scan_at: datetime | None,
    now: datetime,
    cfg: ScheduleConfig,
) -> datetime:
    """Next due time = (last scan, or one full cadence ago if never scanned) +
    cadence + the account's stable jitter offset."""
    anchor = last_scan_at or (now - timedelta(days=cfg.cadence_days))
    base = anchor + timedelta(days=cfg.cadence_days)
    offset = jitter_offset_seconds(account_id, cfg.jitter_minutes * 60)
    return base + timedelta(seconds=offset)


def is_due(
    account_id: uuid.UUID | str,
    last_scan_at: datetime | None,
    now: datetime,
    cfg: ScheduleConfig,
) -> bool:
    return now >= next_run_at(account_id, last_scan_at, now, cfg)
