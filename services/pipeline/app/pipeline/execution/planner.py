"""Planner: flatten gaps, score by impact x control x confidence (config-
weighted), dedup by fix_type (one asset can resolve several queries), and emit a
prioritized backlog.
"""

from __future__ import annotations

from app.pipeline.execution.config import Factors, get_planner_config
from app.pipeline.execution.contracts import Backlog, GapInput, PlanItem


def _score(factors: Factors, weights: Factors) -> float:
    return round(
        (factors.impact**weights.impact)
        * (factors.control**weights.control)
        * (factors.confidence**weights.confidence),
        4,
    )


def plan(gaps: list[GapInput]) -> Backlog:
    cfg = get_planner_config()

    # Group by fix_type — one fix (e.g. a comparison page) resolves many gaps.
    groups: dict[str, list[tuple[GapInput, float]]] = {}
    for gap in gaps:
        factors = cfg.factors_for(gap.gap_type)
        groups.setdefault(gap.fix_type, []).append((gap, _score(factors, cfg.weights)))

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
                    "confidence": f.confidence,
                },
            )
        )

    items.sort(key=lambda it: (-it.score, it.fix_type))
    return Backlog(items=items)
