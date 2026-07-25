"""Turn one parsed answer into mentions rows.

Shared by the live Monitor graph and the re-parse path so the two can never drift
in how they lay out target vs competitor rows. One target-brand row per answer
(carrying the per-answer facts: raw_response + cited_urls), plus one row per
competitor the engine named that run. Competitors resolving to self are skipped —
that is the target, already recorded.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from app.pipeline.contracts import CitationSource, MentionRecord, ParsedMention

Resolver = Callable[[str], tuple[uuid.UUID | None, bool]]


def records_for_answer(
    *,
    prompt_id: uuid.UUID,
    engine: str,
    run: int,
    brand_name: str,
    focal_competitor_id: uuid.UUID | None,
    parsed: ParsedMention,
    cited: list[CitationSource],
    raw_response: str | None,
    resolve: Resolver,
) -> list[MentionRecord]:
    records = [
        MentionRecord(
            prompt_id=prompt_id,
            engine=engine,
            run=run,
            brand=brand_name,
            competitor_id=focal_competitor_id,
            mentioned=parsed.mentioned,
            position=parsed.position,
            sentiment=parsed.sentiment,
            sentiment_score=parsed.sentiment_score,
            cited_urls=cited,
            raw_response=raw_response,
        )
    ]
    for comp in parsed.competitors:
        comp_id, comp_is_self = resolve(comp.brand)
        if comp_is_self:
            continue
        records.append(
            MentionRecord(
                prompt_id=prompt_id,
                engine=engine,
                run=run,
                brand=comp.brand,
                competitor_id=comp_id,
                mentioned=True,
                position=comp.position,
                sentiment=comp.sentiment,
                sentiment_score=None,
            )
        )
    return records
