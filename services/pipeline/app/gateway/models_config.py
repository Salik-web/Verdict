# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Typed loader for config/models.yaml.

The YAML is the single source of truth for task→model mapping, providers,
pricing, and cross-cutting defaults. This module parses it into validated
Pydantic models and resolves a (task, mode) pair to a concrete target.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from app.gateway.types import GatewayMode

# services/pipeline/  (parents: [0]=gateway, [1]=app, [2]=pipeline root)
_PIPELINE_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = _PIPELINE_ROOT / "config" / "models.yaml"
FIXTURES_DIR = _PIPELINE_ROOT / "config" / "fixtures"


class TaskTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    model: str
    fixture_dir: str | None = None
    default_scenario: str | None = None
    # Search-grounded generation (Gemini only, today). Grounded answers reflect
    # what a user sees NOW and carry source URLs; ungrounded ones are
    # training-data recall with no citations. Billed separately from tokens —
    # keep it on `measurement` and off the cheap tasks.
    grounding: bool = False
    # Ask the provider for machine-readable JSON (its native JSON mode). Set it on
    # tasks whose output we parse (processing/generation), NOT on measurement —
    # measurement must stay prose, both because that's what a user sees and because
    # JSON mode cannot be combined with grounding on Gemini 2.5 (the combo is
    # Gemini-3-only and in preview: ai.google.dev/gemini-api/docs/structured-output).
    # Parsing stays fence-tolerant regardless, since providers may ignore this.
    json_output: bool = False
    # Gemini 2.5+ "thinking" budget, in tokens; 0 disables it. Thinking tokens are
    # billed as output AND count against maxOutputTokens, so a reasoning model can
    # spend its whole budget thinking and return a candidate with NO parts — which
    # is exactly how two measurement answers came back empty and were stored as
    # real observations. Extraction needs no reasoning, so processing sets 0.
    # None = leave the provider's default alone.
    thinking_budget: int | None = None
    # Cap on billable searches per grounded request, for providers that bill per
    # SEARCH rather than per prompt (Anthropic's `max_uses`, OpenAI's tool
    # limit). One request can otherwise run many searches, and at $10/1,000 each
    # an uncapped comparative query is the difference between $0.01 and $0.10.
    # None leaves the provider's own default in place.
    max_searches: int | None = None


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # The registry key of the adapter that serves this provider (models.yaml).
    # Not an enum: valid == an adapter is registered under this name, checked
    # with a helpful error at gateway build. Keeps config decoupled from which
    # adapters happen to exist, so a new one is a drop-in.
    type: str
    base_url: str | None = None
    api_key_env: str | None = None
    rpm: int | None = None
    # Hard spacing between consecutive calls to this provider. The token bucket
    # starts full, so `rpm` alone permits an instant burst — which is exactly what
    # free tiers 429 on. Spacing is what makes a free tier survivable.
    min_interval_s: float | None = None


class Price(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # USD per 1,000,000 tokens.
    input: float
    output: float
    # USD per GROUNDED request, charged on top of tokens.
    #
    # This exists because grounded search is NOT billed per token: Gemini 2.5
    # bills "$35 / 1,000 grounded prompts" — a flat fee per request that a
    # per-token model literally cannot express. It dominates the bill (a grounded
    # prompt costs ~$0.035 vs fractions of a cent of tokens), so omitting it makes
    # cost_usd meaningless for the one task that actually costs money.
    #
    # CAVEAT: this is per-PROMPT billing (Gemini 2.5 semantics). Gemini 3 bills per
    # SEARCH QUERY executed, and one call can run several — for a Gemini 3 model
    # this field would need to multiply by len(groundingMetadata.webSearchQueries).
    # See ai.google.dev/gemini-api/docs/pricing.
    grounded_request: float = 0.0


class RetryConfig(BaseModel):
    max_attempts: int = 3
    initial_backoff_s: float = 0.5
    max_backoff_s: float = 8.0
    # Honour a 429's Retry-After header, but never wait longer than
    # max_retry_after_s — past that, fail the scan instead of pinning a worker.
    respect_retry_after: bool = True
    max_retry_after_s: float = 60.0


class CacheConfig(BaseModel):
    enabled: bool = True
    ttl_s: int = 3600
    # Tasks that must NEVER be cache-served. `measurement` belongs here: the whole
    # point of asking each prompt `repeats` times is fresh samples, and the cache
    # key doesn't include the run index — so caching collapses every repeat into
    # one stored answer (and, worse, the repeats become cache hits that skip the
    # cost log). Excluding it makes each repeat a real, independently-logged call.
    exclude_tasks: list[str] = ["measurement"]


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
            grounding=target.grounding,
            json_output=target.json_output,
            thinking_budget=target.thinking_budget,
            max_searches=target.max_searches,
            price=price,
        )


class ResolvedTarget(BaseModel):
    task: str
    provider: str
    provider_config: ProviderConfig
    model: str
    fixture_dir: str | None
    default_scenario: str | None
    grounding: bool = False
    json_output: bool = False
    thinking_budget: int | None = None
    max_searches: int | None = None
    price: Price | None


def load_models_config(path: Path = CONFIG_PATH) -> ModelsConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ModelsConfig.model_validate(data)


@lru_cache
def get_models_config() -> ModelsConfig:
    return load_models_config()
