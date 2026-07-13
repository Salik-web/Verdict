"""Loaders for schedule.yaml and quotas.yaml (data-driven, not inline)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

# services/pipeline/  (parents: [0]=schedule, [1]=pipeline, [2]=app, [3]=root)
PIPELINE_ROOT = Path(__file__).resolve().parents[3]
_CONFIG = PIPELINE_ROOT / "config"


class ScheduleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cadence_days: int
    jitter_minutes: int
    tick_minutes: int


class QuotaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default_monthly_scans: int
    plans: dict[str, int] = {}

    def monthly_scans(self, plan: str | None) -> int:
        if plan is None:
            return self.default_monthly_scans
        return self.plans.get(plan, self.default_monthly_scans)


@lru_cache
def get_schedule_config() -> ScheduleConfig:
    data = yaml.safe_load((_CONFIG / "schedule.yaml").read_text(encoding="utf-8"))
    return ScheduleConfig.model_validate(data)


@lru_cache
def get_quota_config() -> QuotaConfig:
    data = yaml.safe_load((_CONFIG / "quotas.yaml").read_text(encoding="utf-8"))
    return QuotaConfig.model_validate(data)
