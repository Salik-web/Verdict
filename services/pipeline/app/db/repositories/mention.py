"""Tenant-scoped writes for the mentions time-series table."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Mention
from app.pipeline.contracts import MentionRecord


class MentionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def bulk_insert(
        self,
        account_id: uuid.UUID | str,
        scan_id: uuid.UUID | str,
        records: list[MentionRecord],
    ) -> int:
        rows = [
            Mention(
                account_id=_as_uuid(account_id),
                scan_id=_as_uuid(scan_id),
                prompt_id=r.prompt_id,
                engine=r.engine,
                run=r.run,
                brand=r.brand,
                competitor_id=r.competitor_id,
                mentioned=r.mentioned,
                position=r.position,
                sentiment=r.sentiment,
                sentiment_score=r.sentiment_score,
                cited_urls=r.cited_urls,
            )
            for r in records
        ]
        self.session.add_all(rows)
        self.session.flush()
        return len(rows)

    def count_for_scan(
        self, account_id: uuid.UUID | str, scan_id: uuid.UUID | str
    ) -> int:
        return len(
            self.session.scalars(
                select(Mention.id).where(
                    Mention.account_id == _as_uuid(account_id),
                    Mention.scan_id == _as_uuid(scan_id),
                )
            ).all()
        )


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)
