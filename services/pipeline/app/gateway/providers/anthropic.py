# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Anthropic Messages API adapter, with the server-side web search tool.

╔══════════════════════════════════════════════════════════════════════════╗
║ UNVERIFIED AGAINST A LIVE API.                                           ║
║                                                                          ║
║ This adapter was written against the published documentation and is      ║
║ covered by unit tests using recorded response SHAPES. No Anthropic key   ║
║ was available when it was written, so it has never made a real call.     ║
║ Treat the first live scan as the acceptance test. See docs/ENGINES.md.   ║
╚══════════════════════════════════════════════════════════════════════════╝

Why this needs its own adapter rather than `openai_compatible`: the Messages API
differs in three ways that are not cosmetic.

  * `system` is a TOP-LEVEL request parameter, not a message with role="system".
  * `content` is a LIST OF TYPED BLOCKS, not a string. A grounded answer
    interleaves `text`, `server_tool_use`, and `web_search_tool_result` blocks,
    so the answer text is the concatenation of the `text` blocks.
  * usage is `{input_tokens, output_tokens}`, not `{prompt_tokens,
    completion_tokens}`, and carries `server_tool_use.web_search_requests` — the
    number of searches actually billed.

Grounding (platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool):
  tools: [{"type": "web_search_20250305", "name": "web_search", "max_uses": N}]

Billing: $10 per 1,000 searches, PLUS standard token costs — search results are
counted as input tokens. Each search is one use regardless of result count, and
a failed search is not billed. Because one request may run several searches,
this reports the real count via `grounded_units` instead of assuming one.

Citations come back as `web_search_result_location` entries on the text blocks,
carrying `url`, `title` and `cited_text` — **direct publisher URLs**, not
redirect wrappers (see the documented example, which cites
`https://en.wikipedia.org/wiki/Claude_Shannon` verbatim). That is the property
that makes domain-membership checking useful for this engine.
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

# The API version header is required and is a date string, not a semver.
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_WEB_SEARCH_TOOL = "web_search_20250305"


@register_provider("anthropic")
class AnthropicProvider(Provider):
    def __init__(self, retry_config: RetryConfig, timeout_s: float = 120.0) -> None:
        self._retry = retry_config
        # Longer than the chat default: a grounded turn runs searches
        # server-side before it answers.
        self._timeout = timeout_s

    @classmethod
    def from_config(cls, config: ModelsConfig) -> AnthropicProvider:
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

        # system is a top-level param here, NOT a message.
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        turns = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role != "system"
        ]

        payload: dict[str, Any] = {
            "model": target.model,
            # Required by this API. Kept generous so a grounded answer is not
            # cut off mid-sentence — a truncated answer cannot support a
            # "brand absent" observation, so clipping it wastes the call.
            "max_tokens": params.get("max_tokens", 4096),
            "messages": turns,
        }
        if system:
            payload["system"] = system
        if "temperature" in params:
            payload["temperature"] = params["temperature"]

        if target.grounding:
            tool: dict[str, Any] = {
                "type": params.get("web_search_tool", DEFAULT_WEB_SEARCH_TOOL),
                "name": "web_search",
            }
            max_uses = params.get("max_searches", target.max_searches)
            if max_uses:
                tool["max_uses"] = max_uses
            payload["tools"] = [tool]

        resp = post_with_retry(
            f"{cfg.base_url.rstrip('/')}/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_VERSION,
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

        text, sources = _read_content(data.get("content") or [])
        usage_raw = data.get("usage") or {}
        usage = Usage(
            prompt_tokens=int(usage_raw.get("input_tokens") or 0),
            completion_tokens=int(usage_raw.get("output_tokens") or 0),
        )
        searches = int(
            (usage_raw.get("server_tool_use") or {}).get("web_search_requests") or 0
        )
        stop_reason = data.get("stop_reason")
        return ProviderResult(
            text=text,
            usage=usage,
            raw=data,
            citations=[s.url for s in sources],
            sources=sources,
            finish_reason=stop_reason,
            # "max_tokens" is this API's spelling of "cut off".
            truncated=stop_reason == "max_tokens",
            grounded_units=searches,
        )


def _read_content(blocks: list[Any]) -> tuple[str, list[Citation]]:
    """Flatten Messages-API content blocks into (answer text, cited sources).

    A grounded turn interleaves block types, so the answer is the concatenation
    of `text` blocks only — a naive `content[0].text` would return "I'll search
    for..." and drop the actual answer.

    Sources are collected from BOTH places they appear, deduped by URL:
      * `web_search_tool_result` -> `web_search_result` entries (everything the
        search returned), and
      * `citations` on text blocks (`web_search_result_location`, what Claude
        actually cited).
    Preferring only the latter would under-report what grounded the answer;
    preferring only the former would over-report.
    """
    parts: list[str] = []
    seen: dict[str, Citation] = {}

    def remember(url: Any, title: Any) -> None:
        if isinstance(url, str) and url and url not in seen:
            seen[url] = Citation(
                url=url, title=title if isinstance(title, str) else None
            )

    for block in blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")

        if btype == "text":
            if isinstance(block.get("text"), str):
                parts.append(block["text"])
            for citation in block.get("citations") or []:
                if isinstance(citation, dict):
                    remember(citation.get("url"), citation.get("title"))

        elif btype == "web_search_tool_result":
            content = block.get("content")
            # On error `content` is a single object, not a list — a rate-limited
            # search returns HTTP 200 with an error block inside.
            if isinstance(content, list):
                for entry in content:
                    if isinstance(entry, dict) and entry.get("type") == (
                        "web_search_result"
                    ):
                        remember(entry.get("url"), entry.get("title"))

    return "".join(parts), list(seen.values())
