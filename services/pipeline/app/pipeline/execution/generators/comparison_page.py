"""ComparisonPageGenerator: gap + competitor data + verified_facts -> a
structured comparison page (HTML) + FAQ JSON-LD, via the gateway 'generation'
task. Customer-specific claims are declared and later validated against
verified_facts (see validate.py)."""

from __future__ import annotations

import json

from app.gateway import Gateway
from app.gateway.types import Message
from app.pipeline.execution.base import Generator
from app.pipeline.execution.contracts import (
    AssetDraft,
    Claim,
    GeneratorContext,
    PlanItem,
)
from app.pipeline.monitor.config import load_prompt_template


class ComparisonPageGenerator(Generator):
    fix_type = "generate_comparison_page"
    asset_type = "comparison_page"

    def __init__(
        self, gateway: Gateway, scenario: str | None = "comparison_page_asset"
    ) -> None:
        # `scenario` selects the mock fixture; None in dev/prod = real generation.
        self._gateway = gateway
        self._scenario = scenario

    def generate(self, item: PlanItem, context: GeneratorContext) -> AssetDraft:
        competitor = (
            context.competitors[0].name if context.competitors else "competitors"
        )
        facts_block = (
            "\n".join(
                f"- {f.fact_type}/{f.key}: {f.display}" for f in context.verified_facts
            )
            or "(none provided)"
        )

        filled = load_prompt_template("comparison_page").format(
            brand=context.brand_name,
            competitor=competitor,
            prompts=", ".join(str(p) for p in context.target_prompt_ids) or "(general)",
            verified_facts=facts_block,
        )
        res = self._gateway.call(
            "generation",
            [Message(role="user", content=filled)],
            account_id=context.account_id,
            scenario=self._scenario,
        )
        data = json.loads(res.text)
        return AssetDraft(
            asset_type=self.asset_type,
            fix_type=self.fix_type,
            title=data["title"],
            content=data["html"],
            content_kind="html",
            schema_jsonld=data.get("faq_jsonld"),
            claims=[Claim.model_validate(c) for c in data.get("claims", [])],
            target_prompt_ids=context.target_prompt_ids,
        )
