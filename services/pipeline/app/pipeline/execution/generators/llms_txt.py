"""LlmsTxtGenerator: build a /llms.txt from the brand + verified_facts.
Deterministic template (facts only) — no fabricated claims, no LLM needed."""

from __future__ import annotations

from app.pipeline.execution.base import Generator
from app.pipeline.execution.contracts import (
    AssetDraft,
    Claim,
    GeneratorContext,
    PlanItem,
)


class LlmsTxtGenerator(Generator):
    fix_type = "add_llms_txt"
    asset_type = "llms_txt"

    def generate(self, item: PlanItem, context: GeneratorContext) -> AssetDraft:
        lines = [f"# {context.brand_name}", ""]
        if context.brand_aliases:
            lines.append(f"> Also known as: {', '.join(context.brand_aliases)}")
            lines.append("")

        claims: list[Claim] = []
        if context.verified_facts:
            lines.append("## Key facts")
            for f in context.verified_facts:
                lines.append(f"- {f.fact_type}/{f.key}: {f.display}")
                claims.append(
                    Claim(
                        fact_type=f.fact_type, key=f.key, value=f.display, about="self"
                    )
                )
            lines.append("")

        if context.competitors:
            names = ", ".join(c.name for c in context.competitors)
            lines.append(f"## Compared with\n{names}")
            lines.append("")

        return AssetDraft(
            asset_type=self.asset_type,
            fix_type=self.fix_type,
            title=f"/llms.txt for {context.brand_name}",
            content="\n".join(lines),
            content_kind="text",
            claims=claims,
            target_prompt_ids=context.target_prompt_ids,
        )
