# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Typed contracts for the Verification stage.

`SelfMetric` (before) + `SelfMetric` (after) in, `VerificationResult` out — the
comparison is a pure function of those, with no DB or network. The runner loads
the snapshots via repositories and persists the verdict.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class SelfMetric(BaseModel):
    """The target brand's own visibility over a fixed set of prompts, rolled up
    across engines and runs. Computed identically for the before and after scans
    so the two are strictly comparable ("same queries" is the whole point)."""

    model_config = ConfigDict(extra="forbid")
    observations: int = 0  # (prompt, engine, run) answers
    mentioned_count: int = 0
    mention_rate: float = 0.0  # mentioned_count / observations
    avg_position: float | None = None

    @property
    def has_sample(self) -> bool:
        return self.observations > 0


class VerificationResult(BaseModel):
    """The honest verdict — 'no_change' and 'inconclusive' are real outcomes."""

    model_config = ConfigDict(extra="forbid")
    verdict: str  # improved | no_change | regressed | inconclusive
    delta: float  # after.mention_rate - before.mention_rate
    confidence: float  # 0..1
    before: SelfMetric
    after: SelfMetric
    notes: str = ""


class VerificationOutcome(BaseModel):
    """Runner result: the pure comparison plus the DB rows it linked/wrote."""

    model_config = ConfigDict(extra="forbid")
    verification_id: uuid.UUID
    asset_id: uuid.UUID
    scan_before_id: uuid.UUID | None
    scan_after_id: uuid.UUID
    result: VerificationResult
    target_prompt_ids: list[uuid.UUID] = Field(default_factory=list)
