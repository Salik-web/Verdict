"""Tenant-scoped data access for generated assets."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Asset, Verification


class AssetRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        account_id: uuid.UUID | str,
        asset_id: uuid.UUID,
        gap_id: uuid.UUID | None,
        type: str,
        title: str,
        content_ref: str,
        metadata: dict[str, Any],
        target_prompt_ids: list[uuid.UUID],
        status: str,
        validation_state: str,
    ) -> Asset:
        row = Asset(
            id=asset_id,
            account_id=_as_uuid(account_id),
            gap_id=gap_id,
            type=type,
            title=title,
            content_ref=content_ref,
            metadata_=metadata,
            target_prompt_ids=target_prompt_ids,
            status=status,
            validation_state=validation_state,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get(
        self, account_id: uuid.UUID | str, asset_id: uuid.UUID | str
    ) -> Asset | None:
        return self.session.scalars(
            select(Asset).where(
                Asset.account_id == _as_uuid(account_id),
                Asset.id == _as_uuid(asset_id),
            )
        ).first()

    def list_due_for_verification(
        self,
        account_id: uuid.UUID | str,
        shipped_before: datetime,
        limit: int = 50,
    ) -> list[Asset]:
        """Validated assets that shipped before `shipped_before`, carry target
        prompts (nothing to re-measure otherwise), and have no verification yet.
        Tenant-scoped; the beat calls this per account."""
        account_id = _as_uuid(account_id)
        already_verified = select(Verification.id).where(
            Verification.asset_id == Asset.id
        )
        return list(
            self.session.scalars(
                select(Asset)
                .where(
                    Asset.account_id == account_id,
                    Asset.status == "validated",
                    Asset.created_at <= shipped_before,
                    func.coalesce(func.array_length(Asset.target_prompt_ids, 1), 0) > 0,
                    ~already_verified.exists(),
                )
                .order_by(Asset.created_at)
                .limit(limit)
            ).all()
        )


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)
