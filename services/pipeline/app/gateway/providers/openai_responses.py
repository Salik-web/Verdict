# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""OpenAI **Responses API** adapter, with the hosted web_search tool.

╔══════════════════════════════════════════════════════════════════════════╗
║ UNVERIFIED AGAINST A LIVE API.                                           ║
║                                                                          ║
║ Written against the published documentation and covered by unit tests    ║
║ using recorded response SHAPES. No OpenAI key was available when it was  ║
║ written, so it has never made a real call. Treat the first live scan as  ║
║ the acceptance test. See docs/ENGINES.md.                                ║
╚══════════════════════════════════════════════════════════════════════════╝

This exists as a separate adapter because grounded OpenAI is a **different
endpoint**, not a parameter. `/chat/completions` has no web search; the hosted
`web_search` tool lives on `/responses`, which also returns a different
envelope (`output` is a list of typed items, and citations arrive as
`url_citation` annotations on the output text).

An ungrounded OpenAI call would still work through `openai_compatible`, and is
deliberately NOT offered as a measurement engine: an ungrounded answer is
training-data recall, cites nothing, and would silently measure the wrong thing
while looking identical in the database.

Billing (developers.openai.com/api/docs/pricing): the web search tool is
**$10.00 per 1,000 calls**, and search content is billed at the model's standard
INPUT token rate — except gpt-4o-mini and gpt-4.1-mini on the non-preview tool,
which bill search content as a flat 8,000 input tokens per call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.gateway.models_config import ResolvedTarget, RetryConfig
from app.gateway.providers.base import Provider
from app.gateway.providers.http import post_with_retry, resolve_api_key
from app.gateway.providers.registry import register_provider
from app.gateway.types import Citation, Message, ProviderResult, Usage

if TYPE_CHECKING:
    from app.gateway.models_config import ModelsConfig


@register_provider("openai_responses")
class OpenAIResponsesProvider(Provider):
    def __init__(self, retry_config: RetryConfig, timeout_s: float = 120.0) -> None:
        self._retry = retry_config
        self._timeout = timeout_s

    @classmethod
    def from_config(cls, config: ModelsConfig) -> OpenAIResponsesProvider:
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
            # The Responses API accepts the same role/content list as `input`.
            "input": [{"role": m.role, "content": m.content} for m in messages],
        }
        if "temperature" in params:
            payload["temperature"] = params["temperature"]
        if "max_tokens" in params:
            payload["max_output_tokens"] = params["max_tokens"]
        if target.grounding:
            payload["tools"] = [{"type": "web_search"}]

        resp = post_with_retry(
            f"{cfg.base_url.rstrip('/')}/responses",
            headers={
                "Authorization": f"Bearer {api_key}",
                "content-type": "application/json",
            },
            payload=payload,
            retry=self._retry,
            timeout_s=self._timeout,
            provider=target.provider,
            model=target.model,
        )
        resp.raise_for_status()
        data = resp.json()

        text, sources, searches = _read_output(data)
        usage_raw = data.get("usage") or {}
        usage = Usage(
            prompt_tokens=int(usage_raw.get("input_tokens") or 0),
            completion_tokens=int(usage_raw.get("output_tokens") or 0),
        )
        # "incomplete" + reason max_output_tokens is this API's "cut off".
        status = data.get("status")
        incomplete = data.get("incomplete_details") or {}
        truncated = status == "incomplete" and (
            incomplete.get("reason") == "max_output_tokens"
        )
        return ProviderResult(
            text=text,
            usage=usage,
            raw=data,
            citations=[s.url for s in sources],
            sources=sources,
            finish_reason=incomplete.get("reason") or status,
            truncated=truncated,
            grounded_units=searches,
        )


def _read_output(data: dict[str, Any]) -> tuple[str, list[Citation], int]:
    """Flatten a Responses envelope into (text, sources, search count).

    `output` is a list of typed items. A grounded response contains at least a
    `web_search_call` item per search performed and a `message` item whose
    `content` carries `output_text` parts. Citations ride as `url_citation`
    annotations on those parts — direct publisher URLs, with the page title.

    `output_text` (the SDK's flattened convenience field) is preferred for the
    answer when present, because it is exactly the concatenation this would
    otherwise do by hand.
    """
    parts: list[str] = []
    seen: dict[str, Citation] = {}
    searches = 0

    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        itype = item.get("type")

        if itype == "web_search_call":
            searches += 1
            continue

        if itype != "message":
            continue

        for part in item.get("content") or []:
            if not isinstance(part, dict):
                continue
            if isinstance(part.get("text"), str):
                parts.append(part["text"])
            for ann in part.get("annotations") or []:
                if not isinstance(ann, dict):
                    continue
                if ann.get("type") != "url_citation":
                    continue
                url = ann.get("url")
                if isinstance(url, str) and url and url not in seen:
                    title = ann.get("title")
                    seen[url] = Citation(
                        url=url, title=title if isinstance(title, str) else None
                    )

    flattened = data.get("output_text")
    text = flattened if isinstance(flattened, str) and flattened else "".join(parts)
    return text, list(seen.values()), searches
