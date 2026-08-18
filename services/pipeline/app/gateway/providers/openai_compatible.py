# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""OpenAI-compatible chat-completions provider (dev/prod).

Covers any provider exposing the OpenAI /chat/completions shape — Groq,
OpenRouter, DeepSeek, Perplexity, Moonshot/Kimi, OpenAI itself — so one adapter
serves them all; only base_url + api_key_env differ (in config/models.yaml).

Wired but exercised only when keys are present; mock mode never reaches here.
Gemini is NOT served here — it needs Google Search grounding, which has no
OpenAI-compatible equivalent; see providers/gemini.py.

Retry/backoff/429 policy is shared with the Gemini adapter (providers/http.py).

VERIFICATION STATUS: this adapter HAS run live (OpenRouter, generation task).
Its **Perplexity grounded-source path** (`_extract_sources`, reading
`search_results` / `citations`) has NOT — no Perplexity key was available when it
was written, so it is covered only by unit tests against documented response
shapes. In particular, whether Perplexity returns direct publisher URLs or
redirect wrappers is UNCONFIRMED; the pipeline handles both, but the answer
decides how useful third-party-presence checking is for that engine. One live
scan settles it. See docs/ENGINES.md.
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
from app.gateway.types import Citation, Message, ProviderResult, Usage

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
        choice_raw = data["choices"][0]
        choice = choice_raw["message"]["content"]
        usage_raw = data.get("usage", {})
        usage = Usage(
            prompt_tokens=usage_raw.get("prompt_tokens", 0),
            completion_tokens=usage_raw.get("completion_tokens", 0),
            total_tokens=usage_raw.get("total_tokens", 0),
        )
        # `length` is OpenAI's "hit max_tokens". The monitor refuses to build a
        # mentioned=False observation on a cut-off answer, so this signal has to
        # survive the adapter — without it a truncated answer is stored as if it
        # were complete, which is the exact defect the Gemini adapter fixed.
        finish_reason = choice_raw.get("finish_reason")
        sources, citations = _extract_sources(data)
        return ProviderResult(
            text=choice,
            usage=usage,
            raw=data,
            citations=citations,
            sources=sources,
            finish_reason=finish_reason,
            truncated=finish_reason == "length",
        )


def _extract_sources(data: dict[str, Any]) -> tuple[list[Citation], list[str]]:
    """Pull grounded sources out of an OpenAI-shaped response.

    Only search-grounded providers return these; every other provider on this
    adapter simply has neither key, so both lists come back empty. That is why
    this lives here rather than in a Perplexity-specific adapter — the shape is
    additive, and an ungrounded provider is unaffected.

    Perplexity returns two overlapping fields
    (docs.perplexity.ai/api-reference/chat-completions-post):

      * `search_results` — [{title, url, date?, last_updated?, snippet?}].
        Preferred: it carries the PUBLISHER TITLE, which is what lets a
        third-party-presence check work on domain membership alone, with no
        extra HTTP.
      * `citations` — a flat list of URL strings, no titles.

    Both are read: `sources` prefers search_results and falls back to citations
    so a URL is never lost just because the richer field was absent, and
    `citations` stays the plain URL list for back-compat with existing rows.
    """
    results = data.get("search_results")
    sources: list[Citation] = []
    if isinstance(results, list):
        for entry in results:
            if not isinstance(entry, dict):
                continue
            url = entry.get("url")
            if not url:
                continue
            title = entry.get("title")
            sources.append(Citation(url=url, title=title if title else None))

    raw_citations = data.get("citations")
    citations = (
        [c for c in raw_citations if isinstance(c, str)]
        if isinstance(raw_citations, list)
        else []
    )

    if not sources and citations:
        sources = [Citation(url=u) for u in citations]
    if not citations and sources:
        citations = [s.url for s in sources]
    return sources, citations
