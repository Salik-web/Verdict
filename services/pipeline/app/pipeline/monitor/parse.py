# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Parser (LLM-as-judge): extract a structured ParsedMention from an engine
answer, via the gateway 'processing' task. Validated into a typed Pydantic model
at the boundary.
"""

from __future__ import annotations

from app.gateway import Gateway
from app.gateway.types import Message
from app.pipeline.contracts import ParsedMention, ScanContext
from app.pipeline.json_text import extract_json
from app.pipeline.monitor.config import load_prompt_template
from app.pipeline.monitor.guard import apply_membership_guard, build_terms_for


def parse_answer(
    gateway: Gateway,
    context: ScanContext,
    *,
    answer_text: str,
    scenario: str | None,
) -> ParsedMention:
    prompt = load_prompt_template("mention_extraction").format(
        brand=context.brand_name,
        aliases=", ".join(context.brand_aliases) or "(none)",
        competitors=", ".join(c.name for c in context.competitors) or "(none)",
        answer=answer_text,
    )
    res = gateway.call(
        "processing",
        [Message(role="user", content=prompt)],
        account_id=context.account_id,
        scan_id=context.scan_id,
        scenario=scenario,
    )
    # Tolerant: real judges wrap JSON in fences/prose even in JSON mode.
    parsed = ParsedMention.model_validate(extract_json(res.text))
    # Deterministic guard against the parser echoing the competitor list and
    # against null ranks: only brands literally present in the answer survive, and
    # positions come from first-occurrence order. Runs identically on a re-parse.
    return apply_membership_guard(
        parsed,
        answer_text,
        self_terms=[context.brand_name, *context.brand_aliases],
        terms_for=build_terms_for(context),
    )
