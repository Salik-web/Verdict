"""Tenant-scoped data access for gaps (diagnosis output)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Gap as GapRow
from app.pipeline.diagnosis.contracts import Gap


class GapRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def bulk_insert(
        self,
        account_id: uuid.UUID | str,
        scan_id: uuid.UUID | str | None,
        gaps: list[Gap],
    ) -> int:
        rows = [
            GapRow(
                account_id=_as_uuid(account_id),
                scan_id=_as_uuid(scan_id) if scan_id else None,
                gap_type=g.gap_type,
                rank_score=Decimal(str(g.rank_score)),
                status="open",
                # fix_type/layer/severity/summary live in details jsonb — no
                # schema change; the gaps table already exists (Phase 2).
                details={
                    **g.details,
                    "fix_type": g.fix_type,
                    "layer": g.layer,
                    "severity": g.severity,
                    "summary": g.summary,
                },
            )
            for g in gaps
        ]
        self.session.add_all(rows)
        self.session.flush()
        return len(rows)

    def list_for_scan(
        self, account_id: uuid.UUID | str, scan_id: uuid.UUID | str
    ) -> list[GapRow]:
        return list(
            self.session.scalars(
                select(GapRow).where(
                    GapRow.account_id == _as_uuid(account_id),
                    GapRow.scan_id == _as_uuid(scan_id),
                )
            ).all()
        )


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)
