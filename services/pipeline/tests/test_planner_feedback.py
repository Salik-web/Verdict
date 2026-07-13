"""Verification -> planner feedback (pure): learned confidence reweights ranking."""

from __future__ import annotations

import uuid

from app.pipeline.execution.contracts import GapInput
from app.pipeline.execution.planner import plan
from app.pipeline.verification.feedback import confidence_overrides


def test_reducer_needs_enough_samples():
    # One sample is below min_samples -> no override emitted.
    assert confidence_overrides([("blocked_crawler", "improved", 0.8)]) == {}


def test_regressions_lower_confidence_improvements_raise_it():
    good = [("no_owned_comparison_page", "improved", 0.9)] * 3
    bad = [("missing_llms_txt", "regressed", 0.9)] * 3
    overrides = confidence_overrides(good + bad + [("x", "inconclusive", None)])

    # improved history pushes confidence up toward 1.0 (prior was 0.85).
    assert overrides["no_owned_comparison_page"] > 0.85
    # regressed history pulls it down (prior was 0.90).
    assert overrides["missing_llms_txt"] < 0.90
    # inconclusive carries no signal and never appears.
    assert "x" not in overrides


def test_override_can_flip_the_backlog_order():
    gaps = [
        GapInput(
            gap_id=uuid.uuid4(), gap_type="blocked_crawler", fix_type="fix_robots_txt"
        ),
        GapInput(
            gap_id=uuid.uuid4(),
            gap_type="no_owned_comparison_page",
            fix_type="generate_comparison_page",
        ),
    ]
    # Default: robots fix outranks the comparison page.
    assert plan(gaps).items[0].fix_type == "fix_robots_txt"

    # If robots fixes have historically failed, its confidence collapses and the
    # comparison page takes the top slot.
    flipped = plan(gaps, {"blocked_crawler": 0.1})
    assert flipped.items[0].fix_type == "generate_comparison_page"
    top = next(i for i in flipped.items if i.fix_type == "fix_robots_txt")
    assert top.factors["confidence"] == 0.1
