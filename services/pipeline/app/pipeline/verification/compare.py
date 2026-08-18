# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Pure verdict logic for the Verification stage.

No DB, no network: takes the before/after `SelfMetric` snapshots and the config,
returns a typed, honest `VerificationResult`. Kept separate from the runner so the
policy (thresholds, confidence) is unit-testable in isolation.
"""

from __future__ import annotations

from app.pipeline.verification.config import (
    VerificationConfig,
    get_verification_config,
)
from app.pipeline.verification.contracts import SelfMetric, VerificationResult


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def evaluate(
    before: SelfMetric,
    after: SelfMetric,
    cfg: VerificationConfig | None = None,
) -> VerificationResult:
    cfg = cfg or get_verification_config()
    delta = round(after.mention_rate - before.mention_rate, 4)

    sample = min(before.observations, after.observations)
    sample_factor = _clamp01(sample / cfg.full_confidence_observations)
    effect_factor = _clamp01(abs(delta) / cfg.strong_delta)

    # Too small a sample on either side — refuse to call it.
    if (
        before.observations < cfg.min_observations
        or after.observations < cfg.min_observations
    ):
        return VerificationResult(
            verdict="inconclusive",
            delta=delta,
            confidence=round(0.25 * sample_factor, 4),
            before=before,
            after=after,
            notes=(
                f"insufficient sample: need >= {cfg.min_observations} observations "
                f"on both sides (before={before.observations}, "
                f"after={after.observations})"
            ),
        )

    if abs(delta) < cfg.min_delta:
        return VerificationResult(
            verdict="no_change",
            delta=delta,
            # Flat with a big sample => confident it's flat.
            confidence=round(sample_factor * (1.0 - effect_factor), 4),
            before=before,
            after=after,
            notes=f"|delta| {abs(delta):.4f} < min_delta {cfg.min_delta}",
        )

    verdict = "improved" if delta > 0 else "regressed"
    return VerificationResult(
        verdict=verdict,
        delta=delta,
        # Bigger effect + bigger sample => more confident in the direction.
        confidence=round(sample_factor * (0.5 + 0.5 * effect_factor), 4),
        before=before,
        after=after,
        notes=f"self mention-rate {delta:+.4f} on {sample} observations",
    )
