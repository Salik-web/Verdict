"""Tenant-scoped data access for verified_facts (generator source of truth)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import VerifiedFact


class VerifiedFactRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_active(self, account_id: uuid.UUID | str) -> list[VerifiedFact]:
        return list(
            self.session.scalars(
                select(VerifiedFact).where(
                    VerifiedFact.account_id == _as_uuid(account_id),
                    VerifiedFact.is_active.is_(True),
                )
            ).all()
        )

    def get(
        self, account_id: uuid.UUID | str, fact_type: str, key: str
    ) -> VerifiedFact | None:
        return self.session.scalars(
            select(VerifiedFact).where(
                VerifiedFact.account_id == _as_uuid(account_id),
                VerifiedFact.fact_type == fact_type,
                VerifiedFact.key == key,
            )
        ).first()


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)
