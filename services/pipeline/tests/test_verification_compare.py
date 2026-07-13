"""Verification verdict logic (pure): honest before/after with confidence."""

from __future__ import annotations

from app.pipeline.verification.compare import evaluate
from app.pipeline.verification.config import get_verification_config
from app.pipeline.verification.contracts import SelfMetric


def _metric(observations: int, mentioned: int) -> SelfMetric:
    return SelfMetric(
        observations=observations,
        mentioned_count=mentioned,
        mention_rate=(mentioned / observations if observations else 0.0),
    )


def test_improved_with_confidence():
    # 0/15 -> 9/15 self mention-rate: a clear improvement, confident.
    result = evaluate(_metric(15, 0), _metric(15, 9))
    assert result.verdict == "improved"
    assert result.delta > 0
    assert 0.0 < result.confidence <= 1.0


def test_regressed():
    result = evaluate(_metric(20, 16), _metric(20, 4))
    assert result.verdict == "regressed"
    assert result.delta < 0


def test_no_change_is_first_class():
    # A move smaller than min_delta is honestly reported as no_change, not spun.
    cfg = get_verification_config()
    before = _metric(24, 12)  # 0.5
    after = _metric(24, 13)  # ~0.541, delta ~0.041 < min_delta
    result = evaluate(before, after)
    assert abs(result.delta) < cfg.min_delta
    assert result.verdict == "no_change"
    # Flat on a full sample -> we're fairly sure it's flat.
    assert result.confidence > 0.5


def test_small_sample_is_inconclusive():
    result = evaluate(_metric(2, 0), _metric(2, 2))
    assert result.verdict == "inconclusive"
    assert "insufficient sample" in result.notes
    assert result.confidence < 0.3
