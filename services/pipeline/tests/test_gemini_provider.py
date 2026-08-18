# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Gemini adapter: grounded request shape + groundingMetadata -> cited_urls.

The fixture response below is the shape documented at
ai.google.dev/gemini-api/docs/generate-content/google-search — if Google changes
it, this test is what tells us before a real scan silently loses its citations.

No network: the HTTP post is stubbed. Mock mode never reaches this provider.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.gateway.models_config import ProviderConfig, ResolvedTarget, RetryConfig
from app.gateway.providers import gemini as gemini_mod
from app.gateway.providers.gemini import (
    GeminiProvider,
    citation_titles,
    extract_citations,
)
from app.gateway.types import Message

# Verbatim-shaped sample from the docs (uri really is a vertexaisearch redirect).
GROUNDED_RESPONSE: dict[str, Any] = {
    "candidates": [
        {
            "content": {"parts": [{"text": "Spain won Euro 2024."}], "role": "model"},
            "groundingMetadata": {
                "webSearchQueries": ["UEFA Euro 2024 winner"],
                "searchEntryPoint": {"renderedContent": "<style>...</style>"},
                "groundingChunks": [
                    {
                        "web": {
                            "uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/AAA",
                            "title": "uefa.com",
                        }
                    },
                    {
                        "web": {
                            "uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/BBB",
                            "title": "aljazeera.com",
                        }
                    },
                ],
                "groundingSupports": [
                    {
                        "segment": {
                            "startIndex": 0,
                            "endIndex": 20,
                            "text": "Spain won",
                        },
                        "groundingChunkIndices": [0],
                    }
                ],
            },
        }
    ],
    "usageMetadata": {
        "promptTokenCount": 11,
        "candidatesTokenCount": 7,
        "totalTokenCount": 18,
    },
}


def _target(grounding: bool, json_output: bool = False) -> ResolvedTarget:
    return ResolvedTarget(
        task="measurement",
        provider="gemini",
        provider_config=ProviderConfig(
            type="gemini",
            base_url="https://generativelanguage.googleapis.com/v1beta",
            api_key_env="GOOGLE_API_KEY",
        ),
        model="gemini-2.5-flash",
        fixture_dir=None,
        default_scenario=None,
        grounding=grounding,
        json_output=json_output,
        price=None,
    )


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


@pytest.fixture
def captured(monkeypatch):
    """Stub the HTTP layer and capture what we would have sent."""
    sent: dict[str, Any] = {}

    def _fake_post(url, *, headers, payload, retry, timeout_s, provider, model):
        sent["url"] = url
        sent["headers"] = headers
        sent["payload"] = payload
        return _FakeResponse(GROUNDED_RESPONSE)

    monkeypatch.setattr(gemini_mod, "post_with_retry", _fake_post)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    return sent


def test_grounded_request_enables_google_search_tool(captured):
    provider = GeminiProvider(RetryConfig())
    provider.generate(_target(grounding=True), [Message(role="user", content="hi")], {})

    # The documented generateContent shape.
    assert captured["url"].endswith("/models/gemini-2.5-flash:generateContent")
    assert captured["headers"]["x-goog-api-key"] == "test-key"
    assert captured["payload"]["tools"] == [{"google_search": {}}]
    assert captured["payload"]["contents"] == [
        {"role": "user", "parts": [{"text": "hi"}]}
    ]


def test_ungrounded_request_sends_no_tools(captured):
    provider = GeminiProvider(RetryConfig())
    provider.generate(
        _target(grounding=False), [Message(role="user", content="hi")], {}
    )
    # Cheap tasks must not silently buy grounded requests — they're billed apart.
    assert "tools" not in captured["payload"]


def test_system_message_becomes_system_instruction(captured):
    provider = GeminiProvider(RetryConfig())
    provider.generate(
        _target(grounding=True),
        [
            Message(role="system", content="be terse"),
            Message(role="user", content="hi"),
        ],
        {},
    )
    # Gemini has no "system" role: it goes in its own field, not contents.
    assert captured["payload"]["systemInstruction"] == {"parts": [{"text": "be terse"}]}
    assert [c["role"] for c in captured["payload"]["contents"]] == ["user"]


def test_grounding_metadata_becomes_citations_and_usage(captured):
    provider = GeminiProvider(RetryConfig())
    result = provider.generate(
        _target(grounding=True), [Message(role="user", content="hi")], {}
    )

    assert result.text == "Spain won Euro 2024."
    # citations = URLs alone (back-compat).
    assert result.citations == [
        "https://vertexaisearch.cloud.google.com/grounding-api-redirect/AAA",
        "https://vertexaisearch.cloud.google.com/grounding-api-redirect/BBB",
    ]
    # sources = URL + publisher title (the useful GEO signal), order-preserved.
    assert [(s.url, s.title) for s in result.sources] == [
        (
            "https://vertexaisearch.cloud.google.com/grounding-api-redirect/AAA",
            "uefa.com",
        ),
        (
            "https://vertexaisearch.cloud.google.com/grounding-api-redirect/BBB",
            "aljazeera.com",
        ),
    ]
    assert result.usage.prompt_tokens == 11
    assert result.usage.total_tokens == 18


def test_json_mode_is_sent_when_ungrounded(captured):
    provider = GeminiProvider(RetryConfig())
    provider.generate(
        _target(grounding=False, json_output=True),
        [Message(role="user", content="hi")],
        {},
    )
    assert captured["payload"]["generationConfig"]["responseMimeType"] == (
        "application/json"
    )


def test_json_mode_is_suppressed_on_grounded_calls(captured):
    """Structured output + built-in tools is a Gemini-3-only preview, so on 2.5
    the two cannot combine (ai.google.dev/gemini-api/docs/structured-output).
    Sending both would break the call; grounded measurement wants prose anyway."""
    provider = GeminiProvider(RetryConfig())
    provider.generate(
        _target(grounding=True, json_output=True),
        [Message(role="user", content="hi")],
        {},
    )
    assert captured["payload"]["tools"] == [{"google_search": {}}]
    assert "responseMimeType" not in captured["payload"].get("generationConfig", {})


def test_ungrounded_response_has_no_citations():
    plain = {"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}
    assert extract_citations(plain["candidates"][0]) == []


def test_publisher_domains_come_from_titles_not_the_redirect_uris():
    # The uri is a vertexaisearch redirect; the publisher is in .title. That's
    # the real GEO signal, so keep it reachable.
    assert citation_titles(GROUNDED_RESPONSE["candidates"][0]) == [
        "uefa.com",
        "aljazeera.com",
    ]
