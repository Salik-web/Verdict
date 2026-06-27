"""OpenAI-compatible chat-completions provider (dev/prod).

Covers any provider exposing the OpenAI /chat/completions shape — Groq,
OpenRouter, DeepSeek, Perplexity, Moonshot/Kimi, OpenAI itself — so one adapter
serves them all; only base_url + api_key_env differ (in config/models.yaml).

Wired but exercised only when keys are present; mock mode never reaches here.
The Gemini (non-OpenAI) adapter lands alongside real keys.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.gateway.models_config import ResolvedTarget, RetryConfig
from app.gateway.providers.base import Provider
from app.gateway.types import Message, ProviderResult, Usage


class ProviderHTTPError(RuntimeError):
    """Raised for retryable upstream failures (429 / 5xx / transport)."""


class OpenAICompatibleProvider(Provider):
    def __init__(self, retry_config: RetryConfig, timeout_s: float = 30.0) -> None:
        self._retry = retry_config
        self._timeout = timeout_s

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
        api_key = os.environ.get(cfg.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"{cfg.api_key_env} is not set — required for provider "
                f"'{target.provider}' (or run in mock mode)"
            )

        payload: dict[str, Any] = {
            "model": target.model,
            "messages": [m.model_dump() for m in messages],
        }
        for key in ("temperature", "max_tokens", "top_p", "response_format"):
            if key in params:
                payload[key] = params[key]

        return self._post_with_retry(cfg.base_url, api_key, payload)

    def _post_with_retry(
        self, base_url: str, api_key: str, payload: dict[str, Any]
    ) -> ProviderResult:
        # Build the tenacity decorator from config at call time.
        retrying = retry(
            reraise=True,
            stop=stop_after_attempt(self._retry.max_attempts),
            wait=wait_exponential(
                multiplier=self._retry.initial_backoff_s,
                max=self._retry.max_backoff_s,
            ),
            retry=retry_if_exception_type((ProviderHTTPError, httpx.TransportError)),
        )
        return retrying(self._post_once)(base_url, api_key, payload)

    def _post_once(
        self, base_url: str, api_key: str, payload: dict[str, Any]
    ) -> ProviderResult:
        url = f"{base_url.rstrip('/')}/chat/completions"
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if resp.status_code == 429 or resp.status_code >= 500:
            raise ProviderHTTPError(f"{resp.status_code} from {url}: {resp.text[:200]}")
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
