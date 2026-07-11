"""Tenant-scoped data access for prompts."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Prompt


class PromptRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_by_account(
        self, account_id: uuid.UUID | str, *, active_only: bool = False
    ) -> list[Prompt]:
        stmt = select(Prompt).where(Prompt.account_id == _as_uuid(account_id))
        if active_only:
            stmt = stmt.where(Prompt.active.is_(True))
        return list(self.session.scalars(stmt).all())

    def create_many(
        self,
        account_id: uuid.UUID | str,
        texts: list[str],
        *,
        category: str | None = None,
        prompt_group: str | None = None,
    ) -> list[Prompt]:
        rows = [
            Prompt(
                account_id=_as_uuid(account_id),
                text=text,
                category=category,
                prompt_group=prompt_group,
                active=True,
            )
            for text in texts
        ]
        self.session.add_all(rows)
        self.session.flush()
        return rows


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)
