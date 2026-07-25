"""Cost of a grounded call = tokens + a flat per-request search fee.

The per-token model alone reports ~nothing for the most expensive call in the
pipeline: Gemini 2.5 bills $35/1,000 grounded prompts ($0.035 each) on top of
tokens, which no per-token price can express. These tests pin that the flat fee
is charged on grounded calls only, and that it dominates.
"""

from __future__ import annotations

from decimal import Decimal

from app.gateway.cost import compute_cost
from app.gateway.models_config import Price, get_models_config
from app.gateway.types import Usage

# A typical grounded measurement answer: short question, long sourced answer.
USAGE = Usage(prompt_tokens=50, completion_tokens=300)
GEMINI = Price(input=0.30, output=2.50, grounded_request=0.035)


def test_grounded_call_adds_the_flat_search_fee():
    tokens_only = compute_cost(GEMINI, USAGE, grounded=False)
    grounded = compute_cost(GEMINI, USAGE, grounded=True)

    # 50/1M*0.30 + 300/1M*2.50 = 0.000015 + 0.00075 = 0.000765
    assert tokens_only == Decimal("0.000765")
    assert grounded == Decimal("0.035765")  # + $0.035 per grounded prompt
    assert grounded - tokens_only == Decimal("0.035000")


def test_search_fee_dominates_the_token_cost():
    """The point of the whole exercise: grounding is ~98% of a measurement call,
    so pricing tokens alone would have hidden effectively the entire bill."""
    grounded = compute_cost(GEMINI, USAGE, grounded=True)
    fee_share = Decimal("0.035") / grounded
    assert fee_share > Decimal("0.95")


def test_ungrounded_model_never_pays_the_fee():
    cheap = Price(input=0.05, output=0.08)  # no grounded_request configured
    assert compute_cost(cheap, USAGE, grounded=True) == compute_cost(
        cheap, USAGE, grounded=False
    )


def test_dev_config_prices_are_real_not_zero():
    """A free run must still produce true unit economics — 0.0 prices made
    cost_usd meaningless."""
    cfg = get_models_config()
    measurement = cfg.resolve("measurement", "dev")
    assert measurement.grounding is True
    assert measurement.price is not None
    assert measurement.price.grounded_request == 0.035
    assert measurement.price.input > 0 and measurement.price.output > 0

    for task in ("processing", "generation"):
        price = cfg.resolve(task, "dev").price
        assert price is not None, f"{task} has no dev price"
        assert price.input > 0 and price.output > 0, f"{task} priced at zero"


def test_mock_pricing_is_untouched():
    cfg = get_models_config()
    # Mock stays priced like prod so simulated cost rows look realistic, and no
    # mock task is grounded (so none pays the search fee).
    for task in ("measurement", "processing", "generation"):
        target = cfg.resolve(task, "mock")
        assert target.grounding is False
        assert target.price.grounded_request == 0.0
