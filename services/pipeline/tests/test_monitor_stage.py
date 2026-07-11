"""Monitor stage in isolation — pure, mock mode, no DB, no API keys.

Uses the fixture scenario schedule [CW, CW, CW, CI, CI] over 2 prompts x 1 engine
x 5 repeats = 10 answers, so the SoV math is exactly predictable.
"""

from __future__ import annotations

import uuid

import pytest

from app.gateway.cost import NullCostSink
from app.gateway.gateway import build_gateway
from app.gateway.models_config import get_models_config
from app.pipeline.contracts import CompetitorRef, PromptRef, ScanContext
from app.pipeline.monitor.prompts import generate_prompts
from app.pipeline.monitor.stage import run_monitor

ACME = uuid.UUID("00000000-0000-0000-0000-0000000000c0")
GLOBEX = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
INITECH = uuid.UUID("00000000-0000-0000-0000-0000000000c2")


def _mock_gateway():
    return build_gateway(
        mode="mock", cost_sink=NullCostSink(), config=get_models_config()
    )


def _context() -> ScanContext:
    return ScanContext(
        scan_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        brand_name="Acme Analytics",
        brand_aliases=["Acme"],
        competitors=[
            CompetitorRef(
                id=ACME, name="Acme Analytics", aliases=["Acme"], is_self=True
            ),
            CompetitorRef(id=GLOBEX, name="Globex Insights", aliases=["Globex"]),
            CompetitorRef(id=INITECH, name="Initech Metrics", aliases=["Initech"]),
        ],
        prompts=[
            PromptRef(id=uuid.uuid4(), text="Best product analytics tool?"),
            PromptRef(id=uuid.uuid4(), text="Top analytics platforms for SaaS?"),
        ],
        engines=["perplexity_sonar"],
        repeats=5,
    )


def test_stage_emits_one_mention_per_run():
    out = run_monitor(_context(), _mock_gateway())
    # 2 prompts x 1 engine x 5 repeats
    assert len(out.mentions) == 10
    assert all(m.brand == "Acme Analytics" for m in out.mentions)
    assert all(m.competitor_id == ACME for m in out.mentions)
    # 3 of every 5 runs mention Acme (CW), 2 do not (CI).
    assert sum(m.mentioned for m in out.mentions) == 6


def test_share_of_voice_math_is_correct():
    out = run_monitor(_context(), _mock_gateway())
    allrows = {r.brand: r for r in out.share_of_voice if r.engine == "all"}

    # Presence across 10 observations: Acme 6, Globex 10, Initech 10,
    # Mixpanel 6 (CW only), Amplitude 4 (CI only). Total mentions = 36.
    assert allrows["Acme Analytics"].mention_count == 6
    assert allrows["Globex Insights"].mention_count == 10
    assert allrows["Initech Metrics"].mention_count == 10
    assert allrows["Mixpanel"].mention_count == 6
    assert allrows["Amplitude"].mention_count == 4

    assert allrows["Acme Analytics"].mention_rate == pytest.approx(0.6)
    assert allrows["Globex Insights"].mention_rate == pytest.approx(1.0)

    assert allrows["Acme Analytics"].sov_pct == pytest.approx(6 / 36 * 100, abs=1e-3)
    assert allrows["Globex Insights"].sov_pct == pytest.approx(10 / 36 * 100, abs=1e-3)
    assert sum(r.sov_pct for r in allrows.values()) == pytest.approx(100.0, abs=1e-3)

    # Positions from fixtures.
    assert allrows["Acme Analytics"].avg_position == pytest.approx(4.0)
    assert allrows["Globex Insights"].avg_position == pytest.approx(1.0)

    # Identity resolution.
    assert allrows["Acme Analytics"].is_self is True
    assert allrows["Globex Insights"].competitor_id == GLOBEX
    assert (
        allrows["Mixpanel"].competitor_id is None
    )  # detected but not a tracked competitor


def test_prompt_generation_returns_a_pack():
    prompts = generate_prompts(
        _mock_gateway(),
        account_id=uuid.uuid4(),
        brand_name="Acme Analytics",
        competitors=["Globex Insights", "Initech Metrics"],
    )
    assert 25 <= len(prompts) <= 30
    assert all(isinstance(p, str) and p for p in prompts)
