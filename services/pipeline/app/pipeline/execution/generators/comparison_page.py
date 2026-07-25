"""ComparisonPageGenerator: gap + competitor data + verified_facts -> a
structured comparison page (HTML) + FAQ JSON-LD, via the gateway 'generation'
task. Customer-specific claims are declared and later validated against
verified_facts (see validate.py)."""

from __future__ import annotations

import html
from typing import Any

from app.gateway import Gateway
from app.gateway.types import Message
from app.pipeline.execution.base import Generator
from app.pipeline.execution.contracts import (
    AssetDraft,
    Claim,
    GeneratorContext,
    PlanItem,
)
from app.pipeline.json_text import extract_json
from app.pipeline.monitor.config import load_prompt_template


def render_faq_html(faq_jsonld: dict[str, Any] | None) -> str:
    """Render the VISIBLE FAQ section from the FAQPage JSON-LD.

    Deterministic on purpose. The page must show the Q&As to humans, not just
    bury them in structured data — and rendering both from one source means the
    visible text and the markup can never drift apart (Google requires FAQPage
    markup to match visible content, and an earlier version of this generator
    shipped a "See structured data below" placeholder instead of a real FAQ).

    Text is escaped here; finalize_asset still sanitizes the whole document.
    """
    entries = (faq_jsonld or {}).get("mainEntity") or []
    rows: list[str] = []
    for entry in entries:
        question = (entry.get("name") or "").strip()
        answer = ((entry.get("acceptedAnswer") or {}).get("text") or "").strip()
        if not question or not answer:
            continue
        rows.append(f"<dt>{html.escape(question)}</dt><dd>{html.escape(answer)}</dd>")
    if not rows:
        return ""
    return "<h2>FAQ</h2><dl>" + "".join(rows) + "</dl>"


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
        self_block = (
            "\n".join(
                f"- {f.fact_type}/{f.key}: {f.display}" for f in context.self_facts
            )
            or "(none provided)"
        )
        # Fed separately so the model can't mistake a rival's price for ours — and
        # so "no competitor facts" reads as an explicit instruction not to guess.
        competitor_block = (
            "\n".join(
                f"- {f.competitor or 'competitor'} — {f.fact_type}/{f.key}: {f.display}"
                for f in context.competitor_facts
            )
            or "(none provided — do NOT state any competitor pricing or features)"
        )

        filled = load_prompt_template("comparison_page").format(
            brand=context.brand_name,
            competitor=competitor,
            prompts=", ".join(str(p) for p in context.target_prompt_ids) or "(general)",
            verified_facts=self_block,
            competitor_facts=competitor_block,
        )
        res = self._gateway.call(
            "generation",
            [Message(role="user", content=filled)],
            account_id=context.account_id,
            # Attribute the spend to the scan that triggered it — omitting this
            # logs the row with scan_id NULL, so per-scan cost undercounts.
            scan_id=context.scan_id,
            scenario=self._scenario,
        )
        data = extract_json(res.text)
        faq_jsonld = data.get("faq_jsonld")
        # The model returns the Q&As once (as JSON-LD); we render the visible FAQ
        # from them so the page always has a real, human-readable FAQ section that
        # matches the markup exactly.
        content = data["html"] + render_faq_html(faq_jsonld)
        return AssetDraft(
            asset_type=self.asset_type,
            fix_type=self.fix_type,
            title=data["title"],
            content=content,
            content_kind="html",
            schema_jsonld=faq_jsonld,
            claims=[Claim.model_validate(c) for c in data.get("claims", [])],
            target_prompt_ids=context.target_prompt_ids,
        )
