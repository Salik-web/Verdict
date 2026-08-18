# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Close the loop: turn verification history into planner confidence overrides.

The planner scores gaps by impact x control x confidence. `confidence` starts as
a configured prior; once we have verified outcomes for a gap_type, we blend that
prior toward what we actually observed — fixes that reliably improved visibility
get more confidence, fixes that regressed get less. Pure w.r.t. its input list so
it is unit-testable; a thin DB wrapper loads the history.
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from app.pipeline.execution.config import get_planner_config
from app.pipeline.verification.config import get_verification_config

# Directional score per verdict; 'inconclusive' carries no signal and is skipped.
_VERDICT_SCORE = {"improved": 1.0, "no_change": 0.5, "regressed": 0.0}

# (gap_type, verdict, confidence)
VerdictRow = tuple[str, str, float | None]


def confidence_overrides(history: list[VerdictRow]) -> dict[str, float]:
    """Map gap_type -> learned confidence (0..1), for gap_types with enough
    conclusive samples. gap_types without enough history are simply absent, so the
    planner keeps its configured prior for them."""
    fb = get_verification_config().feedback
    planner = get_planner_config()

    scored: dict[str, list[tuple[float, float]]] = defaultdict(list)  # (score, weight)
    for gap_type, verdict, confidence in history:
        if verdict not in _VERDICT_SCORE:
            continue
        weight = float(confidence) if confidence is not None else 0.0
        scored[gap_type].append((_VERDICT_SCORE[verdict], weight))

    overrides: dict[str, float] = {}
    for gap_type, pairs in scored.items():
        n = len(pairs)
        if n < fb.min_samples:
            continue
        total_weight = sum(w for _, w in pairs)
        if total_weight > 0:
            learned = sum(s * w for s, w in pairs) / total_weight
        else:  # every verdict had null confidence — fall back to an equal mean
            learned = sum(s for s, _ in pairs) / n

        prior = planner.factors_for(gap_type).confidence
        blend = min(1.0, n / fb.full_weight_samples)
        adjusted = (1.0 - blend) * prior + blend * learned
        overrides[gap_type] = round(max(fb.confidence_floor, min(1.0, adjusted)), 4)

    return overrides


def confidence_overrides_from_history(
    session, account_id: uuid.UUID | str
) -> dict[str, float]:
    """DB-facing convenience: load this account's verification history and reduce
    it to planner confidence overrides."""
    from app.db.repositories import VerificationRepository

    history = VerificationRepository(session).history_by_gap_type(account_id)
    return confidence_overrides(history)
