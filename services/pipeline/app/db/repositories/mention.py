# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
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
                cited_urls=[c.model_dump() for c in r.cited_urls],
                raw_response_ref=r.raw_response,
            )
            for r in records
        ]
        self.session.add_all(rows)
        self.session.flush()
        return len(rows)

    def cited_sources_for_scan(
        self, account_id: uuid.UUID | str, scan_id: uuid.UUID | str
    ) -> list[dict]:
        """Every distinct source cited across a scan's answers.

        Deduped by URL, preserving the first title seen — the same article is
        cited by many answers, and a domain histogram built on duplicates would
        just count how chatty each engine was.
        """
        rows = self.session.scalars(
            select(Mention).where(
                Mention.account_id == _as_uuid(account_id),
                Mention.scan_id == _as_uuid(scan_id),
            )
        ).all()
        seen: dict[str, dict] = {}
        for row in rows:
            for entry in row.cited_urls or []:
                if isinstance(entry, str):
                    url, title = entry, None
                elif isinstance(entry, dict):
                    url, title = entry.get("url"), entry.get("title")
                else:
                    continue
                if not url or url in seen:
                    continue
                seen[url] = {"url": url, "title": title}
        return list(seen.values())

    def self_stats(
        self,
        account_id: uuid.UUID | str,
        scan_id: uuid.UUID | str,
        prompt_ids: list[uuid.UUID],
        brand: str,
    ) -> tuple[int, int, float | None]:
        """Self-visibility over a fixed prompt set for one scan, as
        (observations, mentioned_count, avg_position). The before/after signal
        verification compares.

        MUST filter to the target `brand`: the mentions table now holds a row per
        competitor as well as the target, so counting all rows would inflate
        observations and wreck the mention-rate. One target row exists per
        (prompt, engine, run), so filtering by brand restores that denominator.
        Empty prompt set -> zero."""
        if not prompt_ids:
            return (0, 0, None)
        rows = self.session.scalars(
            select(Mention).where(
                Mention.account_id == _as_uuid(account_id),
                Mention.scan_id == _as_uuid(scan_id),
                Mention.prompt_id.in_(prompt_ids),
                Mention.brand == brand,
            )
        ).all()
        observations = len(rows)
        positions = [r.position for r in rows if r.mentioned and r.position is not None]
        mentioned_count = sum(1 for r in rows if r.mentioned)
        avg_position = round(sum(positions) / len(positions), 4) if positions else None
        return (observations, mentioned_count, avg_position)

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
