"""Loader for verification.yaml (data-driven, not inline)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

# services/pipeline/  (parents: [0]=verification, [1]=pipeline, [2]=app, [3]=root)
PIPELINE_ROOT = Path(__file__).resolve().parents[3]
_CONFIG = PIPELINE_ROOT / "config"


class FeedbackConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_samples: int
    full_weight_samples: int
    confidence_floor: float


class VerificationScheduleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Hours to wait after an asset ships before re-measuring. 0 = immediately
    # (useful for testing the loop end-to-end without waiting).
    delay_hours: float
    check_every_minutes: int


class VerificationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_delta: float
    min_observations: int
    strong_delta: float
    full_confidence_observations: int
    schedule: VerificationScheduleConfig
    feedback: FeedbackConfig


@lru_cache
def get_verification_config() -> VerificationConfig:
    data = yaml.safe_load((_CONFIG / "verification.yaml").read_text(encoding="utf-8"))
    return VerificationConfig.model_validate(data)
