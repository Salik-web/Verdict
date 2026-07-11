"""Prompt auto-generation: given a category, produce ~25-30 high-intent buyer
prompts via the gateway 'generation' task. Template lives in config/prompts.

Returns plain strings; persistence (writing prompts rows) is the caller's job so
this stays a pure, testable transform.
"""

from __future__ import annotations

import json
import uuid

from app.gateway import Gateway
from app.gateway.types import Message
from app.pipeline.monitor.config import get_monitor_config, load_prompt_template


def generate_prompts(
    gateway: Gateway,
    *,
    account_id: uuid.UUID,
    brand_name: str,
    competitors: list[str],
    category: str | None = None,
    count: int | None = None,
) -> list[str]:
    cfg = get_monitor_config()
    category = category or cfg.default_category
    count = count or cfg.prompt_target_count

    filled = load_prompt_template("prompt_generation").format(
        count=count,
        category=category,
        brand=brand_name,
        competitors=", ".join(competitors) or "(none known)",
    )
    res = gateway.call(
        "generation",
        [Message(role="user", content=filled)],
        account_id=account_id,
        scenario="prompt_pack",
    )
    data = json.loads(res.text)
    prompts = [p.strip() for p in data.get("prompts", []) if p.strip()]
    return prompts
