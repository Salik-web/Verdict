"""robots.txt fixer + llms.txt generator: share the Generator interface, produce
deliverable (validated) text assets."""

from __future__ import annotations

import uuid

from app.pipeline.execution.contracts import (
    GeneratorContext,
    PlanItem,
    VerifiedFactRef,
)
from app.pipeline.execution.generators import LlmsTxtGenerator, RobotsTxtFixer
from app.pipeline.execution.validate import finalize_asset


def _ctx() -> GeneratorContext:
    return GeneratorContext(
        account_id=uuid.uuid4(),
        brand_name="Acme Analytics",
        brand_aliases=["Acme"],
        verified_facts=[
            VerifiedFactRef(
                fact_type="pricing", key="starting_price", display="$0, usage-based"
            ),
        ],
    )


def _item(fix_type: str) -> PlanItem:
    return PlanItem(
        fix_type=fix_type,
        gap_type="x",
        score=1.0,
        gap_ids=[],
        target_prompt_ids=[],
        factors={},
    )


def test_robots_fixer_allows_search_bots():
    draft = RobotsTxtFixer().generate(_item("fix_robots_txt"), _ctx())
    asset = finalize_asset(draft, _ctx())
    assert asset.validation_state == "passed"
    assert "OAI-SearchBot" in asset.content
    assert "PerplexityBot" in asset.content
    assert "Allow: /" in asset.content


def test_llms_txt_uses_only_verified_facts():
    ctx = _ctx()
    draft = LlmsTxtGenerator().generate(_item("add_llms_txt"), ctx)
    asset = finalize_asset(draft, ctx)
    assert asset.validation_state == "passed"  # every claim maps to a verified fact
    assert "# Acme Analytics" in asset.content
    assert "$0, usage-based" in asset.content
