# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
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
    # A scan still pending/running this long after it started is treated as
    # abandoned and marked failed by the sweeper. Must stay comfortably ABOVE
    # celery_task_time_limit_s (the hard kill), or the sweep would race a task
    # that is still legitimately running — free-tier scans are slow by design.
    stale_after_minutes: int = 30
    # How often the beat looks for abandoned scans.
    stale_sweep_every_minutes: int = 10


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
