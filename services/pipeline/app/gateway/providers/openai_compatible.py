"""OpenAI-compatible chat-completions provider (dev/prod).

Covers any provider exposing the OpenAI /chat/completions shape — Groq,
OpenRouter, DeepSeek, Perplexity, Moonshot/Kimi, OpenAI itself — so one adapter
serves them all; only base_url + api_key_env differ (in config/models.yaml).

Wired but exercised only when keys are present; mock mode never reaches here.
Gemini is NOT served here — it needs Google Search grounding, which has no
OpenAI-compatible equivalent; see providers/gemini.py.

Retry/backoff/429 policy is shared with the Gemini adapter (providers/http.py).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.gateway.models_config import ResolvedTarget, RetryConfig
from app.gateway.providers.base import Provider
from app.gateway.providers.http import (
    ProviderHTTPError,
    ProviderRateLimited,
    post_with_retry,
    resolve_api_key,
)
from app.gateway.providers.registry import register_provider
from app.gateway.types import Message, ProviderResult, Usage

if TYPE_CHECKING:
    from app.gateway.models_config import ModelsConfig

__all__ = [
    "OpenAICompatibleProvider",
    "ProviderHTTPError",
    "ProviderRateLimited",
]


@register_provider("openai_compatible")
class OpenAICompatibleProvider(Provider):
    def __init__(self, retry_config: RetryConfig, timeout_s: float = 30.0) -> None:
        self._retry = retry_config
        self._timeout = timeout_s

    @classmethod
    def from_config(cls, config: ModelsConfig) -> OpenAICompatibleProvider:
        return cls(config.retry)

    def generate(
        self,
        target: ResolvedTarget,
        messages: list[Message],
        params: dict[str, Any],
    ) -> ProviderResult:
        cfg = target.provider_config
        if not cfg.base_url or not cfg.api_key_env:
            raise ValueError(
                f"provider '{target.provider}' is missing base_url/api_key_env"
            )
        api_key = resolve_api_key(cfg.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"{cfg.api_key_env} is not set — required for provider "
                f"'{target.provider}' (or run in mock mode). Put it in "
                f"services/pipeline/.env or the process environment."
            )

        payload: dict[str, Any] = {
            "model": target.model,
            "messages": [m.model_dump() for m in messages],
        }
        # Native JSON mode for tasks whose output we parse. Providers may ignore
        # it (or not support it), so callers still parse fence-tolerantly.
        if target.json_output:
            payload["response_format"] = {"type": "json_object"}
        for key in ("temperature", "max_tokens", "top_p", "response_format"):
            if key in params:
                payload[key] = params[key]  # explicit param wins

        url = f"{cfg.base_url.rstrip('/')}/chat/completions"
        resp = post_with_retry(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            payload=payload,
            retry=self._retry,
            timeout_s=self._timeout,
            provider=target.provider,
            model=target.model,
        )
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]["message"]["content"]
        usage_raw = data.get("usage", {})
        usage = Usage(
            prompt_tokens=usage_raw.get("prompt_tokens", 0),
            completion_tokens=usage_raw.get("completion_tokens", 0),
            total_tokens=usage_raw.get("total_tokens", 0),
        )
        return ProviderResult(text=choice, usage=usage, raw=data)
