"""Loaders for planner.yaml and execution.yaml (data-driven, not inline)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

# services/pipeline/  (parents: [0]=execution, [1]=pipeline, [2]=app, [3]=root)
PIPELINE_ROOT = Path(__file__).resolve().parents[3]
_CONFIG = PIPELINE_ROOT / "config"


class Factors(BaseModel):
    model_config = ConfigDict(extra="forbid")
    impact: float
    control: float
    confidence: float


class PlannerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weights: Factors
    default_factors: Factors
    gaps: dict[str, Factors]

    def factors_for(self, gap_type: str) -> Factors:
        return self.gaps.get(gap_type, self.default_factors)


class ExecutionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifacts_dir: str = "artifacts"
    asset_types: dict[str, str] = {}


def _load(name: str) -> dict:
    return yaml.safe_load((_CONFIG / name).read_text(encoding="utf-8"))


@lru_cache
def get_planner_config() -> PlannerConfig:
    return PlannerConfig.model_validate(_load("planner.yaml"))


@lru_cache
def get_execution_config() -> ExecutionConfig:
    return ExecutionConfig.model_validate(_load("execution.yaml"))
