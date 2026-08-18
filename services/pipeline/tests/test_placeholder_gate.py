# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Regression tests for the shipped /llms.txt bug (audit finding #1).

The bug had three independent parts, each of which alone would publish something
false to a customer's site:

  a) the generator hardcoded about="self" for every fact, so a competitor's
     pricing was published as ours;
  b) the placeholder filter lived inside one generator, so another shipped
     "⚠️ ImagineArt's real starting price" AND it validated (the claim matched
     the stored fact exactly);
  c) competitors printed with their raw stored name ("runway").

The generators that originally exhibited this are no longer part of this
distribution, but every mechanism that CAUGHT it is — `sanitize_context`,
`placeholder_violations`, `finalize_asset`, and `CompetitorRef.display_name`.
So these tests drive a minimal stub generator instead. That is the stronger
test anyway: it pins the guarantee the pipeline makes to ANY third-party
generator, rather than the behaviour of one we happen to ship.
"""

from __future__ import annotations

import uuid

import pytest

from app.pipeline.execution.base import Generator
from app.pipeline.execution.contracts import (
    AssetDraft,
    Claim,
    CompetitorRef,
    GapInput,
    GeneratorContext,
    PlanItem,
    VerifiedFactRef,
)
from app.pipeline.execution.facts_gate import (
    placeholder_violations,
    sanitize_context,
)
from app.pipeline.execution.stage import generate_top_fix
from app.pipeline.execution.validate import finalize_asset

ACCOUNT = uuid.uuid4()


class StubGenerator(Generator):
    """Minimal Generator: emits one claim per fact it is given, copying each
    fact's `about` subject verbatim. Stands in for any third-party generator."""

    fix_type = "add_llms_txt"
    asset_type = "llms_txt"

    def generate(self, item: PlanItem, context: GeneratorContext) -> AssetDraft:
        lines = [f"# {context.brand_name}", ""]
        claims: list[Claim] = []
        for f in context.verified_facts:
            attribution = f"{f.competitor} — " if f.competitor else ""
            lines.append(f"- {attribution}{f.fact_type}/{f.key}: {f.display}")
            claims.append(
                Claim(fact_type=f.fact_type, key=f.key, value=f.display, about=f.about)
            )
        if context.competitors:
            names = ", ".join(c.display_name for c in context.competitors)
            lines.append(f"## Compared with\n{names}")
        return AssetDraft(
            asset_type=self.asset_type,
            fix_type=self.fix_type,
            title=f"/llms.txt for {context.brand_name}",
            content="\n".join(lines),
            content_kind="text",
            claims=claims,
            target_prompt_ids=context.target_prompt_ids,
        )


def _context(**over) -> GeneratorContext:
    base = dict(
        account_id=ACCOUNT,
        brand_name="ImagineArt",
        competitors=[
            CompetitorRef(name="runway"),
            CompetitorRef(name="Midjourney"),
        ],
        verified_facts=[],
    )
    base.update(over)
    return GeneratorContext(**base)


def _item(fix_type: str = "add_llms_txt") -> PlanItem:
    return PlanItem(
        fix_type=fix_type,
        gap_type="missing_llms_txt",
        score=1.0,
        gap_ids=[],
        target_prompt_ids=[],
        factors={},
    )


# ── (a) subject fidelity ─────────────────────────────────────────────────
def test_competitor_fact_is_not_relabelled_as_a_self_claim():
    ctx = _context(
        verified_facts=[
            VerifiedFactRef(
                fact_type="pricing",
                key="starting_price",
                display="$9/mo",
                about="self",
            ),
            VerifiedFactRef(
                fact_type="pricing",
                key="competitor_starting_price",
                display="$10/mo",
                about="competitor",
                competitor="Midjourney",
            ),
        ]
    )
    draft = StubGenerator().generate(_item(), ctx)
    subjects = {(c.key, c.about) for c in draft.claims}
    assert subjects == {
        ("starting_price", "self"),
        ("competitor_starting_price", "competitor"),
    }
    # ...and the page attributes it by name rather than implying it is ours.
    assert "Midjourney — pricing/competitor_starting_price: $10/mo" in draft.content

    asset = finalize_asset(draft, ctx)
    assert asset.violations == []
    assert asset.validation_state == "passed"


def test_the_old_behaviour_would_now_fail_validation():
    """Guards the exact defect: relabelling a competitor fact as a self claim."""
    ctx = _context(
        verified_facts=[
            VerifiedFactRef(
                fact_type="pricing",
                key="competitor_starting_price",
                display="$10/mo",
                about="competitor",
                competitor="Midjourney",
            )
        ]
    )
    relabelled = AssetDraft(
        asset_type="llms_txt",
        fix_type="add_llms_txt",
        title="t",
        content="x",
        content_kind="text",
        claims=[
            Claim(
                fact_type="pricing",
                key="competitor_starting_price",
                value="$10/mo",
                about="self",  # what the generator used to do
            )
        ],
    )
    asset = finalize_asset(relabelled, ctx)
    assert asset.status == "rejected"
    assert "wrong subject" in asset.violations[0]


# ── (b) the placeholder gate, for EVERY generator ────────────────────────
def test_placeholder_facts_never_reach_a_generator():
    ctx = _context(
        verified_facts=[
            VerifiedFactRef(
                fact_type="pricing",
                key="starting_price",
                display="⚠️ ImagineArt's real starting price",
            ),
            VerifiedFactRef(
                fact_type="feature", key="headline", display="Text to video"
            ),
        ]
    )
    clean = sanitize_context(ctx)
    assert [f.key for f in clean.verified_facts] == ["headline"]
    assert clean.dropped_placeholder_facts == ["pricing/starting_price"]


def test_self_only_placeholder_account_no_longer_ships():
    """The proof case from the audit: a self-only placeholder account produced
    validation_state=passed and would have published the placeholder verbatim.

    The gate is applied by the STAGE, so it protects a generator that never
    thinks about placeholders at all — which is exactly the stub used here.
    """
    ctx = _context(
        verified_facts=[
            VerifiedFactRef(
                fact_type="pricing",
                key="starting_price",
                display="⚠️ ImagineArt's real starting price",
            )
        ]
    )
    out = generate_top_fix(
        [
            GapInput(
                gap_type="missing_llms_txt",
                fix_type="add_llms_txt",
                details={"fix_type": "add_llms_txt"},
            )
        ],
        ctx,
        registry={"add_llms_txt": StubGenerator()},
    )
    assert "⚠️" not in out.asset.content
    assert "real starting price" not in out.asset.content
    assert out.asset.claims == []


@pytest.mark.parametrize(
    "value", ["⚠️ your real price", "FILL_ME", "TBD", "   ", "TODO: price"]
)
def test_generator_authored_placeholders_are_rejected(value):
    draft = AssetDraft(
        asset_type="llms_txt",
        fix_type="add_llms_txt",
        title="t",
        content=f"# Brand\n- pricing/starting_price: {value}",
        content_kind="text",
        claims=[Claim(fact_type="pricing", key="starting_price", value=value)],
    )
    assert placeholder_violations(draft), f"{value!r} should be caught"


def test_html_bodies_are_not_scanned_for_placeholder_words():
    """A written page may legitimately say "TBD" in prose; only claims and
    plain-text templates are scanned, so good pages aren't falsely rejected."""
    draft = AssetDraft(
        asset_type="comparison_page",
        fix_type="generate_comparison_page",
        title="t",
        content="<p>Their 2027 roadmap is TBD.</p>",
        content_kind="html",
        claims=[],
    )
    assert placeholder_violations(draft) == []


# ── (c) customer-facing names ────────────────────────────────────────────
def test_competitor_display_name_is_used_in_output():
    ctx = _context()
    draft = StubGenerator().generate(_item(), ctx)
    assert "## Compared with\nRunway, Midjourney" in draft.content
    assert "runway" not in draft.content


def test_display_name_never_recases_the_interior():
    assert CompetitorRef(name="HiggsField").display_name == "HiggsField"
    assert CompetitorRef(name="runway").display_name == "Runway"
    # An alias with real casing wins over blind capitalisation.
    assert CompetitorRef(name="openai", aliases=["OpenAI"]).display_name == "OpenAI"
    # ...but only when it is the same name, not a longer product string.
    assert CompetitorRef(name="runway", aliases=["Runway ML"]).display_name == "Runway"
