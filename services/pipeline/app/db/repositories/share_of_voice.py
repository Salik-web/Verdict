# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Tenant-scoped writes for the pre-computed share_of_voice aggregate."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ShareOfVoice
from app.pipeline.contracts import SoVRecord


class ShareOfVoiceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def insert_many(
        self,
        account_id: uuid.UUID | str,
        scan_id: uuid.UUID | str,
        records: list[SoVRecord],
    ) -> int:
        rows = [
            ShareOfVoice(
                account_id=_as_uuid(account_id),
                scan_id=_as_uuid(scan_id),
                brand=r.brand,
                competitor_id=r.competitor_id,
                is_self=r.is_self,
                engine=r.engine,
                mention_count=r.mention_count,
                mention_rate=Decimal(str(r.mention_rate)),
                avg_position=(
                    None if r.avg_position is None else Decimal(str(r.avg_position))
                ),
                sov_pct=Decimal(str(r.sov_pct)),
                details=r.details,
            )
            for r in records
        ]
        self.session.add_all(rows)
        self.session.flush()
        return len(rows)

    def list_for_scan(
        self, account_id: uuid.UUID | str, scan_id: uuid.UUID | str
    ) -> list[ShareOfVoice]:
        return list(
            self.session.scalars(
                select(ShareOfVoice).where(
                    ShareOfVoice.account_id == _as_uuid(account_id),
                    ShareOfVoice.scan_id == _as_uuid(scan_id),
                )
            ).all()
        )


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)
