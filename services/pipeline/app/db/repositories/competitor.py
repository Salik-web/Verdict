# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Tenant-scoped data access for competitors.

Every query filters on account_id — there is no un-scoped read path.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Competitor


class CompetitorRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_by_account(self, account_id: uuid.UUID | str) -> list[Competitor]:
        return list(
            self.session.scalars(
                select(Competitor).where(Competitor.account_id == _as_uuid(account_id))
            ).all()
        )

    def get(
        self, account_id: uuid.UUID | str, competitor_id: uuid.UUID | str
    ) -> Competitor | None:
        return self.session.scalars(
            select(Competitor).where(
                Competitor.account_id == _as_uuid(account_id),
                Competitor.id == _as_uuid(competitor_id),
            )
        ).first()


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)
