"""Repository for llm_cost_log writes (per-call usage/cost)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import LlmCostLog


class LlmCostRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        *,
        account_id: uuid.UUID | str,
        provider: str,
        model: str,
        operation: str | None,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        cost_usd: Decimal,
        mock: bool,
        job_id: uuid.UUID | str | None = None,
        scan_id: uuid.UUID | str | None = None,
    ) -> LlmCostLog:
        row = LlmCostLog(
            account_id=_as_uuid(account_id),
            job_id=_as_uuid(job_id),
            scan_id=_as_uuid(scan_id),
            provider=provider,
            model=model,
            operation=operation,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
            mock=mock,
        )
        self.session.add(row)
        self.session.flush()
        return row


def _as_uuid(value: uuid.UUID | str | None) -> uuid.UUID | None:
    if value is None:
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)
