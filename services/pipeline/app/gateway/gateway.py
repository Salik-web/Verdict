"""The gateway facade — the one entry point for every model call.

    gw = get_gateway()
    res = gw.call("measurement", messages, account_id=acc, scenario="competitor_wins")
    res.text, res.usage, res.cost_usd, res.model

Responsibilities: resolve task→model from config, check cache, rate-limit,
invoke the provider (with fallback), price the result, log it to llm_cost_log,
and cache it. Providers stay thin; this is where the cross-cutting work lives.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from functools import lru_cache
from typing import Any

from app.core.config import get_settings
from app.gateway.cache import CacheBackend, InMemoryTTLCache, cache_key
from app.gateway.cost import CostEntry, CostSink, DbCostSink, compute_cost
from app.gateway.models_config import ModelsConfig, ResolvedTarget, get_models_config
from app.gateway.providers import MockProvider, OpenAICompatibleProvider, Provider
from app.gateway.ratelimit import RateLimiter, TokenBucketRateLimiter
from app.gateway.types import GatewayMode, GatewayResponse, Message

MessageInput = Sequence[Message] | Sequence[dict[str, Any]]


def _coerce_messages(messages: MessageInput) -> list[Message]:
    return [
        m if isinstance(m, Message) else Message.model_validate(m) for m in messages
    ]


class Gateway:
    def __init__(
        self,
        *,
        mode: GatewayMode,
        config: ModelsConfig,
        providers: dict[str, Provider],
        cost_sink: CostSink,
        cache: CacheBackend | None = None,
        cache_ttl_s: int = 3600,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.mode = mode
        self.config = config
        self._providers = providers
        self._cost_sink = cost_sink
        self._cache = cache
        self._cache_ttl_s = cache_ttl_s
        self._rate_limiter = rate_limiter

    def call(
        self,
        task: str,
        messages: MessageInput,
        *,
        account_id: uuid.UUID | str,
        scenario: str | None = None,
        job_id: uuid.UUID | str | None = None,
        scan_id: uuid.UUID | str | None = None,
        **params: Any,
    ) -> GatewayResponse:
        msgs = _coerce_messages(messages)
        target = self.config.resolve(task, self.mode)
        scenario_eff = scenario or target.default_scenario

        key = cache_key(
            task=task,
            mode=self.mode,
            provider=target.provider,
            model=target.model,
            scenario=scenario_eff,
            messages=msgs,
            params=params,
        )
        if self._cache is not None:
            cached = self._cache.get(key)
            if cached is not None:
                return cached  # cache hit = no spend, no new cost row

        if scenario is not None:
            params = {**params, "scenario": scenario}
        result = self._invoke_with_fallback(task, target, msgs, params)

        cost = compute_cost(target.price, result.usage)
        response = GatewayResponse(
            text=result.text,
            usage=result.usage,
            cost_usd=cost,
            model=target.model,
            provider=target.provider,
            mode=self.mode,
            cached=False,
            scenario=scenario_eff,
        )

        self._cost_sink.record(
            CostEntry(
                account_id=_as_uuid(account_id),
                job_id=_as_uuid(job_id),
                scan_id=_as_uuid(scan_id),
                provider=target.provider,
                model=target.model,
                operation=task,
                usage=result.usage,
                cost_usd=cost,
                mock=self.mode == "mock",
            )
        )

        if self._cache is not None:
            self._cache.set(key, response, self._cache_ttl_s)
        return response

    def call_batch(
        self,
        task: str,
        batch: Sequence[MessageInput],
        *,
        account_id: uuid.UUID | str,
        **kwargs: Any,
    ) -> list[GatewayResponse]:
        """Run many requests for one task.

        For now this loops call(); the ~50%-off async Batch API (submit/poll/
        retrieve) is a prod optimization wired when real keys land. Callers code
        against this signature so that swap requires no change here.
        """
        return [self.call(task, m, account_id=account_id, **kwargs) for m in batch]

    # ── internals ───────────────────────────────────────────────────────
    def _invoke_with_fallback(self, task, target, msgs, params):
        try:
            return self._invoke(target, msgs, params)
        except Exception:
            fallback = self.config.resolve_fallback(task, self.mode)
            if fallback is None:
                raise
            return self._invoke(fallback, msgs, params)

    def _invoke(self, target: ResolvedTarget, msgs, params):
        provider = self._providers.get(target.provider_config.type)
        if provider is None:
            raise NotImplementedError(
                f"provider type '{target.provider_config.type}' is not available "
                "in this phase"
            )
        if self._rate_limiter is not None:
            self._rate_limiter.acquire(target.provider)
        return provider.generate(target, msgs, params)


def _as_uuid(value):
    if value is None:
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)


def build_gateway(
    *,
    mode: GatewayMode | None = None,
    cost_sink: CostSink | None = None,
    config: ModelsConfig | None = None,
) -> Gateway:
    settings = get_settings()
    config = config or get_models_config()
    mode = mode or settings.gateway_mode
    providers: dict[str, Provider] = {
        "mock": MockProvider(),
        "openai_compatible": OpenAICompatibleProvider(config.retry),
    }
    cache = InMemoryTTLCache() if config.cache.enabled else None
    rate_limiter = TokenBucketRateLimiter(
        {name: p.rpm for name, p in config.providers.items() if p.rpm}
    )
    if cost_sink is None:
        from app.db.base import SessionLocal

        cost_sink = DbCostSink(SessionLocal)
    return Gateway(
        mode=mode,
        config=config,
        providers=providers,
        cost_sink=cost_sink,
        cache=cache,
        cache_ttl_s=config.cache.ttl_s,
        rate_limiter=rate_limiter,
    )


@lru_cache
def get_gateway() -> Gateway:
    return build_gateway()
