# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Planner: rank by impact x control x confidence, dedup by fix_type."""

from __future__ import annotations

import uuid

from app.pipeline.execution.contracts import GapInput
from app.pipeline.execution.planner import plan


def test_ranks_and_dedups():
    p1, p2, p3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    gaps = [
        GapInput(
            gap_id=uuid.uuid4(), gap_type="missing_llms_txt", fix_type="add_llms_txt"
        ),
        GapInput(
            gap_id=uuid.uuid4(), gap_type="blocked_crawler", fix_type="fix_robots_txt"
        ),
        # Two comparison-page gaps -> deduped into one item, prompt ids merged.
        GapInput(
            gap_id=uuid.uuid4(),
            gap_type="no_owned_comparison_page",
            fix_type="generate_comparison_page",
            prompt_ids=[p1, p2],
        ),
        GapInput(
            gap_id=uuid.uuid4(),
            gap_type="no_owned_comparison_page",
            fix_type="generate_comparison_page",
            prompt_ids=[p2, p3],
        ),
    ]
    backlog = plan(gaps)

    # 3 fix_types -> 3 items (the two comparison gaps merged).
    assert len(backlog.items) == 3
    fix_types = [i.fix_type for i in backlog.items]
    assert fix_types.index("fix_robots_txt") == 0  # highest impact*control*confidence

    comparison = next(
        i for i in backlog.items if i.fix_type == "generate_comparison_page"
    )
    assert set(comparison.target_prompt_ids) == {p1, p2, p3}  # merged, deduped
    assert len(comparison.gap_ids) == 2

    # Strictly descending score.
    scores = [i.score for i in backlog.items]
    assert scores == sorted(scores, reverse=True)
