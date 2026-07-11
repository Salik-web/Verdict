"""Parser (LLM-as-judge): extract a structured ParsedMention from an engine
answer, via the gateway 'processing' task. Validated into a typed Pydantic model
at the boundary.
"""

from __future__ import annotations

from app.gateway import Gateway
from app.gateway.types import Message
from app.pipeline.contracts import ParsedMention, ScanContext
from app.pipeline.monitor.config import load_prompt_template


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
    return ParsedMention.model_validate_json(res.text)
