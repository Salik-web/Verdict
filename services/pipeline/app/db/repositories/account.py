# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Data access for the tenant root (accounts)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Account


class AccountRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, account_id: uuid.UUID | str) -> Account | None:
        return self.session.get(Account, _as_uuid(account_id))

    def get_by_slug(self, slug: str) -> Account | None:
        return self.session.scalars(select(Account).where(Account.slug == slug)).first()

    def list_ids(self) -> list[uuid.UUID]:
        """Every account id — the scheduler iterates these to find due scans."""
        return list(self.session.scalars(select(Account.id)).all())


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)
