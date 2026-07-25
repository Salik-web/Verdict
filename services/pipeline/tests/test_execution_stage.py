"""Execution stage (mock mode, no keys): generate a valid comparison page using
only verified facts, sanitize away scripts, tag target prompts — and reject an
asset with a fabricated (unverified) pricing claim."""

from __future__ import annotations

import uuid

from app.gateway.cost import NullCostSink
from app.gateway.gateway import build_gateway
from app.gateway.models_config import get_models_config
from app.pipeline.execution.contracts import (
    CompetitorRef,
    GapInput,
    GeneratorContext,
    VerifiedFactRef,
)
from app.pipeline.execution.generators import ComparisonPageGenerator
from app.pipeline.execution.registry import build_registry
from app.pipeline.execution.stage import generate_top_fix

PROMPT_A, PROMPT_B = uuid.uuid4(), uuid.uuid4()

FACTS = [
    VerifiedFactRef(
        fact_type="pricing", key="starting_price", display="$0, usage-based"
    ),
    VerifiedFactRef(fact_type="pricing", key="free_tier", display="1M events/mo free"),
    VerifiedFactRef(
        fact_type="feature",
        key="warehouse_native",
        display="Warehouse-native (BigQuery, Snowflake, Redshift)",
    ),
    VerifiedFactRef(
        fact_type="feature",
        key="self_serve_onboarding",
        display="Self-serve onboarding",
    ),
    # The fixture states the rival's price, so that claim needs a verified
    # competitor fact behind it — same rule as our own claims.
    VerifiedFactRef(
        fact_type="pricing",
        key="competitor_price",
        display="$99/mo",
        about="competitor",
        competitor="Globex Insights",
    ),
]

GAP = GapInput(
    gap_id=uuid.uuid4(),
    gap_type="no_owned_comparison_page",
    fix_type="generate_comparison_page",
    prompt_ids=[PROMPT_A, PROMPT_B],
)


def _gateway():
    return build_gateway(
        mode="mock", cost_sink=NullCostSink(), config=get_models_config()
    )


def _context() -> GeneratorContext:
    return GeneratorContext(
        account_id=uuid.uuid4(),
        brand_name="Acme Analytics",
        brand_aliases=["Acme"],
        competitors=[
            CompetitorRef(name="Globex Insights", domain="globex.example.com")
        ],
        verified_facts=FACTS,
        target_prompt_ids=[PROMPT_A, PROMPT_B],
    )


def test_generates_valid_comparison_page():
    out = generate_top_fix([GAP], _context(), _gateway())
    asset = out.asset

    assert out.plan_item.fix_type == "generate_comparison_page"
    assert asset.asset_type == "comparison_page"
    assert asset.validation_state == "passed"
    assert asset.status == "validated"
    assert asset.violations == []

    # XSS defense: the fixture's <script> is stripped.
    assert "<script" not in asset.content.lower()
    assert "alert(" not in asset.content
    # Real content preserved.
    assert "<h1>" in asset.content
    assert "$0, usage-based" in asset.content
    # FAQ schema present.
    assert asset.schema_jsonld["@type"] == "FAQPage"
    # Tagged to its queries.
    assert set(asset.target_prompt_ids) == {PROMPT_A, PROMPT_B}


def test_page_has_a_real_visible_faq_matching_the_jsonld():
    """A12: the FAQ must be readable ON the page, not only in structured data.

    The old generator emitted "See structured data below", which is a dangling
    placeholder to a human and makes the FAQPage markup mismatch the visible
    content. The visible FAQ is now rendered from the same JSON-LD.
    """
    asset = generate_top_fix([GAP], _context(), _gateway()).asset

    assert "see structured data below" not in asset.content.lower()

    # A visible FAQ section survives sanitization...
    assert "<h2>FAQ</h2>" in asset.content
    assert "<dt>" in asset.content and "<dd>" in asset.content

    # ...and every Q&A in the markup is actually on the page.
    for entry in asset.schema_jsonld["mainEntity"]:
        assert entry["name"] in asset.content
        assert entry["acceptedAnswer"]["text"] in asset.content


def test_faq_renderer_escapes_and_tolerates_missing_entries():
    from app.pipeline.execution.generators.comparison_page import render_faq_html

    assert render_faq_html(None) == ""
    assert render_faq_html({"mainEntity": []}) == ""
    # Incomplete entries are skipped rather than rendering half a row.
    assert render_faq_html({"mainEntity": [{"name": "Q?"}]}) == ""

    rendered = render_faq_html(
        {
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": "Is it <b>cheap</b>?",
                    "acceptedAnswer": {"@type": "Answer", "text": "Yes & fast"},
                }
            ]
        }
    )
    assert "&lt;b&gt;cheap&lt;/b&gt;" in rendered  # escaped, not injected
    assert "Yes &amp; fast" in rendered


def _with_scenario(scenario: str):
    gw = _gateway()
    registry = build_registry(gw)
    registry["generate_comparison_page"] = ComparisonPageGenerator(
        gw, scenario=scenario
    )
    return generate_top_fix([GAP], _context(), gw, registry=registry).asset


def test_rejects_unverified_pricing_claim():
    # Tampered fixture: our own pricing claim doesn't match verified_facts.
    asset = _with_scenario("comparison_page_bad_pricing")

    assert asset.validation_state == "failed"
    assert asset.status == "rejected"
    assert any("starting_price" in v for v in asset.violations)
    assert any("$49/month" in v for v in asset.violations)


def test_rejects_invented_competitor_claim():
    """A competitor's price the model made up must be rejected, not published.

    Same path as a self claim: no verified competitor fact -> no claim. This is
    the rule that stops us printing a rival's pricing from imagination.
    """
    asset = _with_scenario("comparison_page_bad_competitor")

    assert asset.validation_state == "failed"
    assert asset.status == "rejected"
    assert any(
        "unverified competitor claim" in v and "competitor_seat_price" in v
        for v in asset.violations
    ), asset.violations


def test_a_self_fact_cannot_back_a_competitor_claim():
    """Subject must match: our $0 pricing must never be published as theirs."""
    from app.pipeline.execution.contracts import AssetDraft, Claim
    from app.pipeline.execution.validate import finalize_asset

    draft = AssetDraft(
        asset_type="comparison_page",
        fix_type="generate_comparison_page",
        title="t",
        content="<p>x</p>",
        # Real key, real value — but it's OUR fact, dressed up as the rival's.
        claims=[
            Claim(
                fact_type="pricing",
                key="starting_price",
                value="$0, usage-based",
                about="competitor",
            )
        ],
    )
    asset = finalize_asset(draft, _context())

    assert asset.status == "rejected"
    assert any("wrong subject" in v for v in asset.violations), asset.violations


def test_verified_competitor_claim_is_allowed():
    # The happy path: the fixture's $99/mo IS backed by a competitor fact.
    asset = generate_top_fix([GAP], _context(), _gateway()).asset
    assert asset.status == "validated"
    assert any(c.about == "competitor" for c in asset.claims)
    assert "$99/mo" in asset.content
