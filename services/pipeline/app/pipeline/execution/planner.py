# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Planner: flatten gaps, score by impact x control x confidence (config-
weighted), dedup by fix_type (one asset can resolve several queries), and emit a
prioritized backlog.
"""

from __future__ import annotations

from app.pipeline.execution.config import Factors, get_planner_config
from app.pipeline.execution.contracts import Backlog, GapInput, PlanItem


def _score(factors: Factors, weights: Factors, confidence: float) -> float:
    return round(
        (factors.impact**weights.impact)
        * (factors.control**weights.control)
        * (confidence**weights.confidence),
        4,
    )


def plan(
    gaps: list[GapInput],
    confidence_overrides: dict[str, float] | None = None,
) -> Backlog:
    """Rank + dedup gaps into a backlog. `confidence_overrides` (gap_type ->
    learned confidence, from the Verification feedback loop) replaces the
    configured confidence prior where present, so the plan adapts to what past
    fixes actually moved."""
    cfg = get_planner_config()
    overrides = confidence_overrides or {}

    def confidence_for(gap_type: str) -> float:
        if gap_type in overrides:
            return overrides[gap_type]
        return cfg.factors_for(gap_type).confidence

    # Drop weakly-detected gaps from RANKING (not from storage — they stay in the
    # gaps table for the report). A single-page inference must never become the
    # top fix: that is exactly how a false "no comparison page" scored 0.81 and
    # shipped a page for a site that already had 51 of them.
    rankable = [
        g
        for g in gaps
        if float((g.details or {}).get("detection_confidence", 1.0))
        >= cfg.min_detection_confidence
    ]

    # Group by fix_type — one fix (e.g. a comparison page) resolves many gaps.
    groups: dict[str, list[tuple[GapInput, float]]] = {}
    for gap in rankable:
        factors = cfg.factors_for(gap.gap_type)
        score = _score(factors, cfg.weights, confidence_for(gap.gap_type))
        groups.setdefault(gap.fix_type, []).append((gap, score))

    items: list[PlanItem] = []
    for fix_type, scored in groups.items():
        best_gap, best_score = max(scored, key=lambda gs: gs[1])
        gap_ids = [g.gap_id for g, _ in scored if g.gap_id is not None]
        prompt_ids: list = []
        for g, _ in scored:
            for pid in g.prompt_ids:
                if pid not in prompt_ids:
                    prompt_ids.append(pid)
        f = cfg.factors_for(best_gap.gap_type)
        items.append(
            PlanItem(
                fix_type=fix_type,
                gap_type=best_gap.gap_type,
                score=best_score,
                gap_ids=gap_ids,
                target_prompt_ids=prompt_ids,
                factors={
                    "impact": f.impact,
                    "control": f.control,
                    "confidence": confidence_for(best_gap.gap_type),
                },
            )
        )

    items.sort(key=lambda it: (-it.score, it.fix_type))
    return Backlog(items=items)
