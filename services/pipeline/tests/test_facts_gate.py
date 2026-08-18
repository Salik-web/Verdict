# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Minimum-facts gate + competitor selection.

The real failure this covers: the generator was told "Competitor: HiggsField"
(competitors[0]) while every verified fact was about Midjourney, and all four
facts were unfilled placeholders. It dutifully produced a page whose every row
said "not publicly disclosed". Refuse instead, with a reason the customer can act
on.
"""

from __future__ import annotations

import uuid

import pytest

from app.pipeline.execution.base import Generator
from app.pipeline.execution.contracts import (
    AssetDraft,
    CompetitorRef,
    GeneratorContext,
    PlanItem,
    VerifiedFactRef,
)
from app.pipeline.execution.facts_gate import (
    GenerationBlocked,
    is_placeholder,
    require_facts_for_comparison,
    select_competitor,
)


class _StubGenerator(Generator):
    """Stands in for whatever generator a downstream product registers. This
    repo ships none, so tests about the STAGE's routing supply their own."""

    fix_type = "generate_comparison_page"
    asset_type = "comparison_page"

    def generate(self, item: PlanItem, context: GeneratorContext) -> AssetDraft:
        return AssetDraft(
            asset_type=self.asset_type,
            fix_type=self.fix_type,
            title="t",
            content="<p>ok</p>",
            content_kind="html",
        )


def _ctx(self_facts=(), comp_facts=(), competitors=("HiggsField", "Midjourney")):
    return GeneratorContext(
        account_id=uuid.uuid4(),
        brand_name="Imagine Art",
        competitors=[CompetitorRef(name=n) for n in competitors],
        verified_facts=[*self_facts, *comp_facts],
    )


def _self(display: str) -> VerifiedFactRef:
    return VerifiedFactRef(
        fact_type="pricing", key="starting_price", display=display, about="self"
    )


def _comp(name: str, display: str) -> VerifiedFactRef:
    return VerifiedFactRef(
        fact_type="pricing",
        key="competitor_starting_price",
        display=display,
        about="competitor",
        competitor=name,
    )


# ── placeholder detection ────────────────────────────────────────────────
@pytest.mark.parametrize(
    "display",
    [
        "⚠️ ImagineArt's real starting price",
        "FILL_ME-at-least-10-chars",
        "TODO",
        "<your price here>",
        "   ",
    ],
)
def test_placeholders_are_not_facts(display):
    assert is_placeholder(_self(display)) is True


def test_a_real_value_is_a_fact():
    assert is_placeholder(_self("$19/month")) is False


# ── competitor selection ─────────────────────────────────────────────────
def test_competitor_with_facts_is_chosen_over_the_first_one():
    """The exact bug: competitors[0] is HiggsField, but the facts are about
    Midjourney — compare against the one we can actually speak to."""
    ctx = _ctx(
        self_facts=[_self("$19/month")],
        comp_facts=[_comp("Midjourney", "$10/month")],
    )
    assert select_competitor(ctx) == "Midjourney"
    competitor, facts = require_facts_for_comparison(ctx)
    assert competitor == "Midjourney"
    assert [f.display for f in facts] == ["$10/month"]


def test_placeholder_competitor_facts_do_not_qualify():
    ctx = _ctx(
        self_facts=[_self("$19/month")],
        comp_facts=[_comp("Midjourney", "⚠️ Midjourney's real published price")],
    )
    with pytest.raises(GenerationBlocked) as e:
        require_facts_for_comparison(ctx)
    assert "Midjourney" in e.value.reason
    assert e.value.detail["missing"] == "competitor_facts"


# ── the gate ─────────────────────────────────────────────────────────────
def test_blocked_when_no_real_self_facts():
    ctx = _ctx(
        self_facts=[_self("⚠️ your real price")],
        comp_facts=[_comp("Midjourney", "$10/month")],
    )
    with pytest.raises(GenerationBlocked) as e:
        require_facts_for_comparison(ctx)
    assert e.value.detail["missing"] == "self_facts"
    assert "Imagine Art" in e.value.reason


def test_blocked_reason_names_the_competitor_to_supply_facts_for():
    """The customer should see what to do, not a hollow page."""
    ctx = _ctx(self_facts=[_self("$19/month")], comp_facts=[])
    with pytest.raises(GenerationBlocked) as e:
        require_facts_for_comparison(ctx)
    assert "provide facts about" in e.value.reason


def test_blocked_when_no_competitors_configured():
    ctx = _ctx(self_facts=[_self("$19/month")], competitors=())
    with pytest.raises(GenerationBlocked) as e:
        require_facts_for_comparison(ctx)
    assert e.value.detail["missing"] == "competitors"


def test_passes_with_real_facts_on_both_sides():
    ctx = _ctx(
        self_facts=[_self("$19/month")],
        comp_facts=[_comp("Midjourney", "$10/month")],
        competitors=("Midjourney",),
    )
    competitor, facts = require_facts_for_comparison(ctx)
    assert competitor == "Midjourney" and len(facts) == 1


# ── advisory gaps must not crash execution ───────────────────────────────
def test_top_gap_without_a_generator_falls_through_to_a_buildable_fix():
    """page_noindex outranks everything but is fixed by editing the customer's
    HTML, not by generating an asset. Execution must ship the next actionable
    fix instead of raising 'no generator registered'."""
    from app.gateway.cost import NullCostSink
    from app.gateway.gateway import build_gateway
    from app.gateway.models_config import get_models_config
    from app.pipeline.execution.contracts import GapInput
    from app.pipeline.execution.stage import generate_top_fix

    gw = build_gateway(
        mode="mock", cost_sink=NullCostSink(), config=get_models_config()
    )
    ctx = _ctx(
        self_facts=[_self("$0, usage-based")],
        comp_facts=[_comp("Globex Insights", "$99/mo")],
        competitors=("Globex Insights",),
    )

    def gap(gap_type: str, fix_type: str) -> GapInput:
        return GapInput(
            gap_id=uuid.uuid4(),
            gap_type=gap_type,
            fix_type=fix_type,
            prompt_ids=[],
            details={},
        )

    out = generate_top_fix(
        [
            gap("page_noindex", "remove_noindex"),
            gap("no_owned_comparison_page", "generate_comparison_page"),
        ],
        ctx,
        gw,
        # A generator IS registered for the lower-ranked fix, so the fall-through
        # is what is under test rather than the empty-registry case.
        registry={"generate_comparison_page": _StubGenerator()},
    )
    assert out.backlog.items[0].fix_type == "remove_noindex"  # still ranked #1
    assert out.plan_item.fix_type == "generate_comparison_page"  # but this ships
    # ...and the one we skipped past is reported, not silently dropped.
    assert out.unsupported_fix_types == ["remove_noindex"]


def test_only_advisory_gaps_reports_a_reason_instead_of_crashing():
    from app.gateway.cost import NullCostSink
    from app.gateway.gateway import build_gateway
    from app.gateway.models_config import get_models_config
    from app.pipeline.execution.contracts import GapInput
    from app.pipeline.execution.stage import generate_top_fix

    gw = build_gateway(
        mode="mock", cost_sink=NullCostSink(), config=get_models_config()
    )
    ctx = _ctx(self_facts=[_self("$0")], competitors=("Globex Insights",))
    gaps = [
        GapInput(
            gap_id=uuid.uuid4(),
            gap_type="page_noindex",
            fix_type="remove_noindex",
            prompt_ids=[],
            details={},
        )
    ]
    out = generate_top_fix(gaps, ctx, gw, registry={})
    # An advisory-only backlog is an ordinary reported outcome, never a raise:
    # nothing crashed, and the caller is told exactly what it could not build.
    assert out.produced_asset is False
    assert out.unsupported_fix_types == ["remove_noindex"]
    assert "remove_noindex" in out.reason
    # The ranking survives, because the backlog is the deliverable here.
    assert [i.fix_type for i in out.backlog.items] == ["remove_noindex"]
