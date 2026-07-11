"""Tenant-scoped data access for scans."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Scan


class ScanRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, account_id: uuid.UUID | str, scan_id: uuid.UUID | str) -> Scan | None:
        return self.session.scalars(
            select(Scan).where(
                Scan.account_id == _as_uuid(account_id),
                Scan.id == _as_uuid(scan_id),
            )
        ).first()


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)
