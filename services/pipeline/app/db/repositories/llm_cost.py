# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Repository for llm_cost_log writes (per-call usage/cost)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import LlmCostLog


class LlmCostRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def summary(
        self,
        account_id: uuid.UUID | str,
        *,
        since: datetime | None = None,
    ) -> dict[str, Any]:
        """Tenant-scoped cost roll-up for the internal cost endpoint: totals plus
        a per-provider/model breakdown. Pre-aggregated in SQL, never row-by-row."""
        account_id = _as_uuid(account_id)
        conds = [LlmCostLog.account_id == account_id]
        if since is not None:
            conds.append(LlmCostLog.created_at >= since)

        totals = self.session.execute(
            select(
                func.count(LlmCostLog.id),
                func.coalesce(func.sum(LlmCostLog.cost_usd), 0),
                func.coalesce(func.sum(LlmCostLog.total_tokens), 0),
                func.count(LlmCostLog.id).filter(LlmCostLog.mock.is_(True)),
            ).where(*conds)
        ).one()

        by_provider = self.session.execute(
            select(
                LlmCostLog.provider,
                LlmCostLog.model,
                func.count(LlmCostLog.id),
                func.coalesce(func.sum(LlmCostLog.cost_usd), 0),
                func.coalesce(func.sum(LlmCostLog.total_tokens), 0),
            )
            .where(*conds)
            .group_by(LlmCostLog.provider, LlmCostLog.model)
            .order_by(func.sum(LlmCostLog.cost_usd).desc())
        ).all()

        calls, cost_usd, tokens, mock_calls = totals
        return {
            "account_id": str(account_id),
            "calls": int(calls),
            "cost_usd": float(cost_usd),
            "total_tokens": int(tokens),
            "mock_calls": int(mock_calls),
            "real_calls": int(calls) - int(mock_calls),
            "by_model": [
                {
                    "provider": provider,
                    "model": model,
                    "calls": int(n),
                    "cost_usd": float(c),
                    "total_tokens": int(t),
                }
                for provider, model, n, c, t in by_provider
            ],
        }

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
        cached: bool = False,
        status: str = "ok",
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
            cached=cached,
            status=status,
        )
        self.session.add(row)
        self.session.flush()
        return row


def _as_uuid(value: uuid.UUID | str | None) -> uuid.UUID | None:
    if value is None:
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)
