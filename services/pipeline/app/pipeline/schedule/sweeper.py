# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Stale-scan sweeper: fail scans whose worker died.

Celery's soft time limit raises SoftTimeLimitExceeded *inside* the task, so the
stage wrapper still runs and marks the scan failed. That covers a task that is
alive but slow. It does not cover the process simply ceasing to exist — an OOM
kill, a container eviction, a `docker compose down` mid-scan, or the hard time
limit firing. In those cases nothing raises, no handler runs, and the scan sits
at `running` forever, which a user cannot tell apart from one that is merely
slow. A scan is expected to take minutes, so "still running" is not suspicious
on its face.

This sweep is the backstop: anything still pending/running past a generous
deadline is marked failed with an explicit reason, so the row reflects reality
and the account's quota is not consumed by a ghost.

The deadline is deliberately well above the hard task limit — see
`stale_after_minutes` in config/schedule.yaml. Sweeping too eagerly would kill
legitimate slow scans, which on a free tier are slow by design (deliberate
spacing between rate-limited calls).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.db.base import SessionLocal
from app.db.repositories import ScanRepository
from app.pipeline.schedule.config import get_schedule_config

log = logging.getLogger(__name__)

_REASON = (
    "Scan exceeded {minutes} minutes with no completion. Its worker most likely "
    "died (OOM kill, container restart, or the hard task time limit) — a process "
    "that stops existing cannot mark its own scan failed. Re-run the scan."
)


def sweep_stale_scans(now: datetime | None = None) -> dict[str, Any]:
    """Mark every over-deadline pending/running scan as failed.

    Returns what it swept so the beat log is auditable rather than silent.
    """
    cfg = get_schedule_config()
    minutes = cfg.stale_after_minutes
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(minutes=minutes)

    swept: list[dict[str, str]] = []
    with SessionLocal() as session:
        repo = ScanRepository(session)
        for scan in repo.list_stale(cutoff):
            repo.mark_failed(scan.account_id, scan.id, _REASON.format(minutes=minutes))
            swept.append(
                {
                    "scan_id": str(scan.id),
                    "account_id": str(scan.account_id),
                    "status_was": scan.status,
                }
            )
        session.commit()

    if swept:
        log.warning(
            "swept %d stale scan(s) older than %d minutes: %s",
            len(swept),
            minutes,
            [s["scan_id"] for s in swept],
        )
    return {"swept": len(swept), "cutoff_minutes": minutes, "scans": swept}
