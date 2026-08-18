# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Cost calculation and cost sinks.

Cost is usage x configured price; every gateway call writes one row to
llm_cost_log via a CostSink. DbCostSink persists; NullCostSink collects in
memory (for tests / no-DB runs).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel

from app.gateway.models_config import Price
from app.gateway.types import Usage

_PER_TOKENS = Decimal(1_000_000)


def compute_cost(
    price: Price | None,
    usage: Usage,
    *,
    grounded: bool = False,
    grounded_units: int = 1,
) -> Decimal:
    """Tokens x price, plus a flat per-request fee for grounded search.

    Grounded search is billed per REQUEST, not per token (Gemini 2.5: $35/1,000
    grounded prompts), and that flat fee dwarfs the token cost — so a pure
    per-token calculation reports roughly zero for the most expensive call in the
    pipeline. `grounded` comes from the resolved target, so an ungrounded call on
    the same model never pays it.
    """
    if price is None:
        return Decimal("0")
    inp = Decimal(usage.prompt_tokens) / _PER_TOKENS * Decimal(str(price.input))
    out = Decimal(usage.completion_tokens) / _PER_TOKENS * Decimal(str(price.output))
    total = inp + out
    if grounded:
        # `grounded_units` is how many billable searches actually ran. Gemini 2.5
        # bills per prompt (1); Anthropic and OpenAI bill per search, and one
        # request can run several. A provider that does not report a count falls
        # back to 1 rather than to 0, so a missing field never zeroes the fee.
        units = grounded_units if grounded_units and grounded_units > 0 else 1
        total += Decimal(str(price.grounded_request)) * units
    return total.quantize(Decimal("0.000001"))


class CostEntry(BaseModel):
    account_id: uuid.UUID
    job_id: uuid.UUID | None = None
    scan_id: uuid.UUID | None = None
    provider: str
    model: str
    operation: str | None
    usage: Usage
    cost_usd: Decimal
    mock: bool
    # Complete-ledger flags: cached=True means served from cache (no provider
    # call, cost 0); status 'error' means the call raised. Both still get a row.
    cached: bool = False
    status: str = "ok"


class CostSink:
    def record(self, entry: CostEntry) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class NullCostSink(CostSink):
    """Keeps entries in memory; useful when there is no DB."""

    def __init__(self) -> None:
        self.entries: list[CostEntry] = []

    def record(self, entry: CostEntry) -> None:
        self.entries.append(entry)


class DbCostSink(CostSink):
    """Writes each call to llm_cost_log in its own short-lived session."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def record(self, entry: CostEntry) -> None:
        from app.db.repositories.llm_cost import LlmCostRepository

        with self._session_factory() as session:
            LlmCostRepository(session).record(
                account_id=entry.account_id,
                job_id=entry.job_id,
                scan_id=entry.scan_id,
                provider=entry.provider,
                model=entry.model,
                operation=entry.operation,
                prompt_tokens=entry.usage.prompt_tokens,
                completion_tokens=entry.usage.completion_tokens,
                total_tokens=entry.usage.total_tokens,
                cost_usd=entry.cost_usd,
                mock=entry.mock,
                cached=entry.cached,
                status=entry.status,
            )
            session.commit()
