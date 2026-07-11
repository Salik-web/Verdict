"""Tenant-scoped data access for scans."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Scan


class ScanRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, account_id: uuid.UUID | str, scan_id: uuid.UUID | str) -> Scan | None:
        return self.session.scalars(
            select(Scan).where(
                Scan.account_id == _as_uuid(account_id),
                Scan.id == _as_uuid(scan_id),
            )
        ).first()

    # ── lifecycle ────────────────────────────────────────────────────────
    def mark_running(
        self,
        account_id: uuid.UUID | str,
        scan_id: uuid.UUID | str,
        engine_set: list[str],
    ) -> Scan | None:
        scan = self.get(account_id, scan_id)
        if scan is not None:
            scan.status = "running"
            scan.started_at = datetime.now(UTC)
            scan.engine_set = engine_set
            self.session.flush()
        return scan

    def mark_completed(
        self,
        account_id: uuid.UUID | str,
        scan_id: uuid.UUID | str,
        stats: dict[str, Any],
    ) -> Scan | None:
        scan = self.get(account_id, scan_id)
        if scan is not None:
            scan.status = "completed"
            scan.finished_at = datetime.now(UTC)
            scan.stats = stats
            self.session.flush()
        return scan

    def mark_failed(
        self,
        account_id: uuid.UUID | str,
        scan_id: uuid.UUID | str,
        error: str,
    ) -> Scan | None:
        scan = self.get(account_id, scan_id)
        if scan is not None:
            scan.status = "failed"
            scan.finished_at = datetime.now(UTC)
            scan.error = error[:2000]
            self.session.flush()
        return scan


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)
