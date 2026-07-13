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

    def create(
        self,
        account_id: uuid.UUID | str,
        *,
        triggered_by: str | None = None,
        status: str = "pending",
    ) -> Scan:
        """Create a scan row (used by the scheduler and the verification re-scan;
        the TS API creates its own via Drizzle)."""
        scan = Scan(
            account_id=_as_uuid(account_id),
            status=status,
            engine_set=[],
            triggered_by=triggered_by,
        )
        self.session.add(scan)
        self.session.flush()
        return scan

    def last_created_at(self, account_id: uuid.UUID | str) -> datetime | None:
        """created_at of the account's most recent scan (any status) — the anchor
        the scheduler measures cadence from."""
        return self.session.scalars(
            select(Scan.created_at)
            .where(Scan.account_id == _as_uuid(account_id))
            .order_by(Scan.created_at.desc())
            .limit(1)
        ).first()

    def count_since(self, account_id: uuid.UUID | str, since: datetime) -> int:
        """Scans created at/after `since` — the quota check's usage counter."""
        return len(
            self.session.scalars(
                select(Scan.id).where(
                    Scan.account_id == _as_uuid(account_id),
                    Scan.created_at >= since,
                )
            ).all()
        )

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
