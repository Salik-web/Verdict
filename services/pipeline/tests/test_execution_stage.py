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


def test_rejects_unverified_pricing_claim():
    # Force the tampered fixture: pricing claim doesn't match verified_facts.
    gw = _gateway()
    registry = build_registry(gw)
    registry["generate_comparison_page"] = ComparisonPageGenerator(
        gw, scenario="comparison_page_bad_pricing"
    )

    out = generate_top_fix([GAP], _context(), gw, registry=registry)
    asset = out.asset

    assert asset.validation_state == "failed"
    assert asset.status == "rejected"
    assert any("starting_price" in v for v in asset.violations)
    assert any("$49/month" in v for v in asset.violations)
