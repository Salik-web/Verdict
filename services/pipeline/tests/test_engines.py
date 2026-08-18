# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Anthropic and OpenAI grounded adapters.

**These tests exercise recorded response SHAPES, not a live API.** No Anthropic
or OpenAI key was available when the adapters were written, so what is pinned
here is the parsing contract against the published documentation. The first live
scan is the acceptance test — see docs/ENGINES.md for the verification status of
each engine.

What the shapes are taken from:
  * Anthropic: platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool
  * OpenAI:    developers.openai.com/api/docs/pricing (billing) and the
               Responses API output envelope.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.gateway.cost import compute_cost
from app.gateway.models_config import get_models_config
from app.gateway.providers.anthropic import AnthropicProvider, _read_content
from app.gateway.providers.openai_responses import (
    OpenAIResponsesProvider,
    _read_output,
)
from app.gateway.types import Message, Usage

# ── Anthropic: interleaved content blocks ────────────────────────────────
CLAUDE_RESPONSE: dict[str, Any] = {
    "role": "assistant",
    "id": "msg_a930390d3a",
    "stop_reason": "end_turn",
    "content": [
        {"type": "text", "text": "I'll search for that. "},
        {
            "type": "server_tool_use",
            "id": "srvtoolu_01",
            "name": "web_search",
            "input": {"query": "best ai image generators"},
        },
        {
            "type": "web_search_tool_result",
            "tool_use_id": "srvtoolu_01",
            "content": [
                {
                    "type": "web_search_result",
                    "url": "https://zapier.com/blog/best-ai-image-generator/",
                    "title": "The best AI image generators",
                    "page_age": "April 30, 2026",
                    "encrypted_content": "Eqgf...",
                }
            ],
        },
        {
            "type": "text",
            "text": "Midjourney and ImagineArt lead the field.",
            "citations": [
                {
                    "type": "web_search_result_location",
                    "url": "https://www.imagine.art/blogs/midjourney-alternatives",
                    "title": "9 Best Midjourney Alternatives",
                    "cited_text": "ImagineArt is a strong alternative…",
                    "encrypted_index": "Eo8B...",
                }
            ],
        },
    ],
    "usage": {
        "input_tokens": 6039,
        "output_tokens": 931,
        "server_tool_use": {"web_search_requests": 3},
    },
}


def test_claude_answer_is_every_text_block_not_just_the_first():
    """A grounded turn opens with "I'll search for…" before the real answer.
    Reading content[0] would store the preamble and drop the answer entirely."""
    text, _ = _read_content(CLAUDE_RESPONSE["content"])
    assert text == "I'll search for that. Midjourney and ImagineArt lead the field."


def test_claude_sources_come_from_both_results_and_citations():
    """Search results are what was retrieved; citations are what was used. Only
    reading one under-reports what actually grounded the answer."""
    _, sources = _read_content(CLAUDE_RESPONSE["content"])
    urls = {s.url for s in sources}
    assert urls == {
        "https://zapier.com/blog/best-ai-image-generator/",
        "https://www.imagine.art/blogs/midjourney-alternatives",
    }
    titles = {s.title for s in sources}
    assert "9 Best Midjourney Alternatives" in titles


def test_claude_citations_are_direct_publisher_urls_not_wrappers():
    """The property that makes domain-membership checking work for this engine.
    Contrast Gemini, whose citations are vertexaisearch redirect wrappers."""
    from app.pipeline.diagnosis.citations import is_redirect_wrapper

    _, sources = _read_content(CLAUDE_RESPONSE["content"])
    assert sources, "fixture must have sources for this assertion to mean anything"
    assert all(not is_redirect_wrapper(s.url) for s in sources)


def test_claude_search_error_block_does_not_raise():
    """A rate-limited search returns HTTP 200 with an error OBJECT where the
    result LIST would be. Iterating it blindly would crash the scan."""
    blocks = [
        {"type": "text", "text": "hi"},
        {
            "type": "web_search_tool_result",
            "tool_use_id": "x",
            "content": {
                "type": "web_search_tool_result_error",
                "error_code": "max_uses_exceeded",
            },
        },
    ]
    text, sources = _read_content(blocks)
    assert text == "hi"
    assert sources == []


def _claude_call(monkeypatch, response: dict[str, Any]):
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return response

    captured: dict[str, Any] = {}

    def fake_post(url, *, headers, payload, **kw):
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        return _Resp()

    monkeypatch.setattr("app.gateway.providers.anthropic.post_with_retry", fake_post)
    monkeypatch.setattr(
        "app.gateway.providers.anthropic.resolve_api_key", lambda env: "sk-ant-test"
    )
    config = get_models_config()
    provider = AnthropicProvider.from_config(config)
    target = config.resolve("measurement_anthropic", "dev")
    result = provider.generate(
        target,
        [
            Message(role="system", content="Be brief."),
            Message(role="user", content="q"),
        ],
        {},
    )
    return result, captured


def test_claude_request_shape(monkeypatch):
    _, captured = _claude_call(monkeypatch, CLAUDE_RESPONSE)
    payload = captured["payload"]

    # system is a TOP-LEVEL param, not a message — the single most common way to
    # get this API wrong.
    assert payload["system"] == "Be brief."
    assert [m["role"] for m in payload["messages"]] == ["user"]
    assert payload["max_tokens"] > 0
    # Grounding is a server-side tool, and max_uses caps per-search spend.
    assert payload["tools"] == [
        {"type": "web_search_20250305", "name": "web_search", "max_uses": 3}
    ]
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert captured["url"].endswith("/messages")


def test_claude_usage_and_search_count(monkeypatch):
    result, _ = _claude_call(monkeypatch, CLAUDE_RESPONSE)
    assert result.usage.prompt_tokens == 6039
    assert result.usage.completion_tokens == 931
    # Billed per SEARCH: this request ran three.
    assert result.grounded_units == 3
    assert result.truncated is False


def test_claude_max_tokens_is_truncation(monkeypatch):
    cut = {**CLAUDE_RESPONSE, "stop_reason": "max_tokens"}
    result, _ = _claude_call(monkeypatch, cut)
    assert result.truncated is True


def test_multi_search_requests_are_priced_per_search(monkeypatch):
    """Three searches at $10/1,000 is $0.03, not $0.01. Pricing per REQUEST
    would undercount every comparative query."""
    target = get_models_config().resolve("measurement_anthropic", "dev")
    one = compute_cost(target.price, Usage(), grounded=True, grounded_units=1)
    three = compute_cost(target.price, Usage(), grounded=True, grounded_units=3)
    assert three == one * 3
    assert three == Decimal("0.030000")


# ── OpenAI Responses: typed output items ─────────────────────────────────
OPENAI_RESPONSE: dict[str, Any] = {
    "id": "resp_1",
    "status": "completed",
    "output": [
        {"type": "web_search_call", "id": "ws_1", "status": "completed"},
        {"type": "web_search_call", "id": "ws_2", "status": "completed"},
        {
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": "Midjourney and ImagineArt are the leaders.",
                    "annotations": [
                        {
                            "type": "url_citation",
                            "url": "https://zapier.com/blog/best-ai-image-generator/",
                            "title": "The best AI image generators",
                            "start_index": 0,
                            "end_index": 10,
                        }
                    ],
                }
            ],
        },
    ],
    "usage": {"input_tokens": 1200, "output_tokens": 300},
}


def test_openai_output_text_and_citations():
    text, sources, searches = _read_output(OPENAI_RESPONSE)
    assert text == "Midjourney and ImagineArt are the leaders."
    assert [s.url for s in sources] == [
        "https://zapier.com/blog/best-ai-image-generator/"
    ]
    assert sources[0].title == "The best AI image generators"
    # One billable call per web_search_call item.
    assert searches == 2


def test_openai_prefers_the_flattened_output_text_when_present():
    payload = {**OPENAI_RESPONSE, "output_text": "flattened answer"}
    text, _, _ = _read_output(payload)
    assert text == "flattened answer"


def test_openai_ungrounded_response_has_no_sources():
    payload = {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "hi", "annotations": []}],
            }
        ],
        "usage": {},
    }
    text, sources, searches = _read_output(payload)
    assert text == "hi"
    assert sources == []
    assert searches == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"output": "not-a-list"},
        {"output": [None, 3]},
        {"output": [{"type": "message", "content": "not-a-list"}]},
        {"output": [{"type": "message", "content": [{"annotations": "nope"}]}]},
        {},
    ],
)
def test_openai_malformed_output_does_not_raise(payload):
    text, sources, searches = _read_output(payload)
    assert isinstance(text, str)
    assert sources == []
    assert searches >= 0


def _openai_call(monkeypatch, response: dict[str, Any]):
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return response

    captured: dict[str, Any] = {}

    def fake_post(url, *, headers, payload, **kw):
        captured["url"] = url
        captured["payload"] = payload
        return _Resp()

    monkeypatch.setattr(
        "app.gateway.providers.openai_responses.post_with_retry", fake_post
    )
    monkeypatch.setattr(
        "app.gateway.providers.openai_responses.resolve_api_key",
        lambda env: "sk-test",
    )
    config = get_models_config()
    provider = OpenAIResponsesProvider.from_config(config)
    target = config.resolve("measurement_openai", "dev")
    return provider.generate(target, [Message(role="user", content="q")], {}), captured


def test_openai_uses_the_responses_endpoint_with_the_search_tool(monkeypatch):
    """Grounded OpenAI is a DIFFERENT ENDPOINT, not a parameter on
    /chat/completions. Getting this wrong yields an ungrounded answer that looks
    identical in the database while measuring training recall."""
    _, captured = _openai_call(monkeypatch, OPENAI_RESPONSE)
    assert captured["url"].endswith("/responses")
    assert captured["payload"]["tools"] == [{"type": "web_search"}]


def test_openai_incomplete_is_truncation(monkeypatch):
    cut = {
        **OPENAI_RESPONSE,
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
    }
    result, _ = _openai_call(monkeypatch, cut)
    assert result.truncated is True
    assert result.finish_reason == "max_output_tokens"


def test_openai_grounded_units_drive_the_search_fee(monkeypatch):
    result, _ = _openai_call(monkeypatch, OPENAI_RESPONSE)
    assert result.grounded_units == 2
    target = get_models_config().resolve("measurement_openai", "dev")
    cost = compute_cost(
        target.price, result.usage, grounded=True, grounded_units=result.grounded_units
    )
    # 2 searches x $0.01, plus tokens.
    assert cost > Decimal("0.02")


# ── availability: all four engines are independently gated ───────────────
def test_every_measurement_engine_is_gated_on_its_own_key(monkeypatch):
    """A user with one key must get that one engine, not an error and not the
    others silently attempted."""
    from app.gateway.availability import task_status

    for var in (
        "GOOGLE_API_KEY",
        "PERPLEXITY_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)

    class _NoKeys:
        deployment_mode = "self_hosted"

    monkeypatch.setattr("app.gateway.credentials.get_settings", lambda: _NoKeys())

    expected = {
        "measurement": "GOOGLE_API_KEY",
        "measurement_perplexity": "PERPLEXITY_API_KEY",
        "measurement_openai": "OPENAI_API_KEY",
        "measurement_anthropic": "ANTHROPIC_API_KEY",
    }
    for task, env in expected.items():
        status = task_status(task, "dev")
        assert status.available is False, task
        assert status.missing_key_env == env, task

    # ...and every one of them still runs in mock mode with no keys at all.
    for task in expected:
        assert task_status(task, "mock").available is True
