"""Loaders for the diagnosis data-driven config: ai_bots.yaml, gap_taxonomy.yaml,
diagnosis.yaml. Nothing here is inline in logic (principle 3)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

# services/pipeline/  (parents: [0]=diagnosis, [1]=pipeline, [2]=app, [3]=root)
_PIPELINE_ROOT = Path(__file__).resolve().parents[3]
_CONFIG = _PIPELINE_ROOT / "config"


# ── ai_bots.yaml ─────────────────────────────────────────────────────────
class BotDef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    token: str
    category: Literal["training", "search"]
    vendor: str | None = None


class TrapDef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    training: str
    search: str
    message: str


class BotRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bots: list[BotDef]
    traps: list[TrapDef] = []


# ── gap_taxonomy.yaml ────────────────────────────────────────────────────
class GapDef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    layer: str
    fix_type: str
    base_rank: float
    label: str


class GapTaxonomy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gaps: dict[str, GapDef]
    severity_weights: dict[str, float]


# ── diagnosis.yaml ───────────────────────────────────────────────────────
class ScraperConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_agent: str
    timeout_s: float = 10
    max_pages_per_scan: int = 10
    max_redirects: int = 3
    max_bytes: int = 2_000_000
    rate_limit_delay_s: float = 0.3
    respect_robots: bool = True


class FetcherConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # auto = fixture in mock gateway mode, http otherwise.
    mode: Literal["auto", "http", "fixture"] = "auto"
    fixtures_dir: str = "fixtures/site"

    def fixtures_path(self) -> Path:
        return _CONFIG / self.fixtures_dir


class DiagnosisConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fetcher: FetcherConfig = FetcherConfig()
    scraper: ScraperConfig
    llms_txt: dict
    freshness: dict


def _load(name: str) -> dict:
    return yaml.safe_load((_CONFIG / name).read_text(encoding="utf-8"))


@lru_cache
def get_bot_registry() -> BotRegistry:
    return BotRegistry.model_validate(_load("ai_bots.yaml"))


@lru_cache
def get_gap_taxonomy() -> GapTaxonomy:
    return GapTaxonomy.model_validate(_load("gap_taxonomy.yaml"))


@lru_cache
def get_diagnosis_config() -> DiagnosisConfig:
    return DiagnosisConfig.model_validate(_load("diagnosis.yaml"))
