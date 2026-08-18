# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Tenant-scoped data access for verifications (before/after proof for assets)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Asset, Gap, Verification


class VerificationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        account_id: uuid.UUID | str,
        asset_id: uuid.UUID | str,
        scan_before_id: uuid.UUID | None,
        scan_after_id: uuid.UUID | None,
        before_metrics: dict[str, Any],
        after_metrics: dict[str, Any],
        confidence: float | None,
        verdict: str,
    ) -> Verification:
        row = Verification(
            account_id=_as_uuid(account_id),
            asset_id=_as_uuid(asset_id),
            scan_before_id=scan_before_id,
            scan_after_id=scan_after_id,
            before_metrics=before_metrics,
            after_metrics=after_metrics,
            confidence=None if confidence is None else Decimal(str(confidence)),
            verdict=verdict,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def history_by_gap_type(
        self, account_id: uuid.UUID | str
    ) -> list[tuple[str, str, float | None]]:
        """(gap_type, verdict, confidence) for every verification whose asset is
        tied to a gap — the raw signal the planner-feedback reducer consumes."""
        rows = self.session.execute(
            select(Gap.gap_type, Verification.verdict, Verification.confidence)
            .join(Asset, Verification.asset_id == Asset.id)
            .join(Gap, Asset.gap_id == Gap.id)
            .where(Verification.account_id == _as_uuid(account_id))
        ).all()
        return [
            (gap_type, verdict, None if confidence is None else float(confidence))
            for gap_type, verdict, confidence in rows
        ]


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)
