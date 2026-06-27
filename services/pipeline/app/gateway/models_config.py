"""Typed loader for config/models.yaml.

The YAML is the single source of truth for task→model mapping, providers,
pricing, and cross-cutting defaults. This module parses it into validated
Pydantic models and resolves a (task, mode) pair to a concrete target.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

from app.gateway.types import GatewayMode

# services/pipeline/  (parents: [0]=gateway, [1]=app, [2]=pipeline root)
_PIPELINE_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = _PIPELINE_ROOT / "config" / "models.yaml"
FIXTURES_DIR = _PIPELINE_ROOT / "config" / "fixtures"

ProviderType = Literal["mock", "openai_compatible", "gemini"]


class TaskTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    model: str
    fixture_dir: str | None = None
    default_scenario: str | None = None


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: ProviderType
    base_url: str | None = None
    api_key_env: str | None = None
    rpm: int | None = None


class Price(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: float
    output: float


class RetryConfig(BaseModel):
    max_attempts: int = 3
    initial_backoff_s: float = 0.5
    max_backoff_s: float = 8.0


class CacheConfig(BaseModel):
    enabled: bool = True
    ttl_s: int = 3600


class ModelsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default_mode: GatewayMode = "mock"
    tasks: dict[str, dict[GatewayMode, TaskTarget]]
    fallbacks: dict[str, dict[GatewayMode, TaskTarget]] = {}
    providers: dict[str, ProviderConfig]
    pricing: dict[str, Price] = {}
    retry: RetryConfig = RetryConfig()
    cache: CacheConfig = CacheConfig()

    # ── resolution ──────────────────────────────────────────────────────
    def resolve(self, task: str, mode: GatewayMode) -> ResolvedTarget:
        if task not in self.tasks:
            raise KeyError(f"unknown task '{task}'; known tasks: {sorted(self.tasks)}")
        if mode not in self.tasks[task]:
            raise KeyError(f"task '{task}' has no entry for mode '{mode}'")
        return self._build(task, self.tasks[task][mode])

    def resolve_fallback(self, task: str, mode: GatewayMode) -> ResolvedTarget | None:
        target = self.fallbacks.get(task, {}).get(mode)
        return self._build(task, target) if target else None

    def _build(self, task: str, target: TaskTarget) -> ResolvedTarget:
        if target.provider not in self.providers:
            raise KeyError(
                f"task '{task}' references unknown provider '{target.provider}'"
            )
        price = self.pricing.get(f"{target.provider}/{target.model}")
        return ResolvedTarget(
            task=task,
            provider=target.provider,
            provider_config=self.providers[target.provider],
            model=target.model,
            fixture_dir=target.fixture_dir,
            default_scenario=target.default_scenario,
            price=price,
        )


class ResolvedTarget(BaseModel):
    task: str
    provider: str
    provider_config: ProviderConfig
    model: str
    fixture_dir: str | None
    default_scenario: str | None
    price: Price | None


def load_models_config(path: Path = CONFIG_PATH) -> ModelsConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ModelsConfig.model_validate(data)


@lru_cache
def get_models_config() -> ModelsConfig:
    return load_models_config()
