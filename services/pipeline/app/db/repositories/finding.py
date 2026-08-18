# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Tenant-scoped data access for diagnosis findings (the checks' full record)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DiagnosisFinding as FindingRow
from app.pipeline.diagnosis.contracts import Finding


class FindingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def bulk_insert(
        self,
        account_id: uuid.UUID | str,
        scan_id: uuid.UUID | str | None,
        findings: list[Finding],
    ) -> int:
        rows = [
            FindingRow(
                account_id=_as_uuid(account_id),
                scan_id=_as_uuid(scan_id) if scan_id else None,
                layer=f.layer,
                code=f.code,
                ok=f.ok,
                severity=f.severity,
                summary=f.summary,
                gap_type=f.gap_type,
                # `status` is defaulted from `ok` by the contract's validator, so
                # it is never None by the time it reaches here.
                status=f.status
                or ("confirmed_present" if f.ok else "confirmed_absent"),
                confidence=Decimal(str(f.confidence)),
                from_absence=f.from_absence,
                detail=f.detail,
                evidence=[e.model_dump(mode="json") for e in f.evidence],
            )
            for f in findings
        ]
        self.session.add_all(rows)
        self.session.flush()
        return len(rows)

    def list_for_scan(
        self, account_id: uuid.UUID | str, scan_id: uuid.UUID | str
    ) -> list[FindingRow]:
        return list(
            self.session.scalars(
                select(FindingRow)
                .where(
                    FindingRow.account_id == _as_uuid(account_id),
                    FindingRow.scan_id == _as_uuid(scan_id),
                )
                .order_by(FindingRow.id)
            ).all()
        )

    def history(
        self, account_id: uuid.UUID | str, code: str, limit: int = 20
    ) -> list[FindingRow]:
        """How one check has behaved over time — the regression question ("this
        used to raise a gap; when did it stop, and on what basis?")."""
        return list(
            self.session.scalars(
                select(FindingRow)
                .where(
                    FindingRow.account_id == _as_uuid(account_id),
                    FindingRow.code == code,
                )
                .order_by(FindingRow.created_at.desc())
                .limit(limit)
            ).all()
        )


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)
