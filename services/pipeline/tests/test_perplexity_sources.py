# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Grounded-source extraction on the OpenAI-compatible adapter.

Perplexity Sonar is grounded by default and returns its sources in two
overlapping fields (docs.perplexity.ai/api-reference/chat-completions-post):

  * `search_results` — [{title, url, date?, last_updated?, snippet?}]
  * `citations`      — a flat list of URL strings

Until this existed the adapter read neither, so a grounded Perplexity answer
arrived with zero citations and the whole Diagnosis layer — which is driven by
cited URLs — had nothing to work with.

These tests drive the adapter with recorded response SHAPES rather than a live
call. That is a deliberate limitation, not an oversight: no Perplexity key is
available in this environment, so the parsing contract is what can be pinned
here. Whether the live API returns direct publisher URLs or redirect wrappers is
NOT settled by these tests — see docs/ENGINES.md.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.gateway.models_config import get_models_config
from app.gateway.providers.openai_compatible import (
    OpenAICompatibleProvider,
    _extract_sources,
)
from app.gateway.types import Message

# A realistic Sonar response, trimmed to the fields the adapter reads.
SONAR_RESPONSE: dict[str, Any] = {
    "id": "chatcmpl-x",
    "model": "sonar",
    "choices": [
        {
            "index": 0,
            "finish_reason": "stop",
            "message": {
                "role": "assistant",
                "content": "The leading options are Midjourney and ImagineArt.",
            },
        }
    ],
    "usage": {"prompt_tokens": 12, "completion_tokens": 30, "total_tokens": 42},
    "citations": [
        "https://www.imagine.art/blogs/midjourney-alternatives",
        "https://zapier.com/blog/best-ai-image-generator/",
    ],
    "search_results": [
        {
            "title": "9 Best Midjourney Alternatives",
            "url": "https://www.imagine.art/blogs/midjourney-alternatives",
            "date": "2026-05-01",
        },
        {
            "title": "The best AI image generators",
            "url": "https://zapier.com/blog/best-ai-image-generator/",
        },
    ],
}


def test_search_results_become_sources_with_publisher_titles():
    sources, citations = _extract_sources(SONAR_RESPONSE)

    assert [s.url for s in sources] == [
        "https://www.imagine.art/blogs/midjourney-alternatives",
        "https://zapier.com/blog/best-ai-image-generator/",
    ]
    # The TITLE is the load-bearing part: it is what a third-party-presence
    # check reads instead of issuing its own HTTP request.
    assert [s.title for s in sources] == [
        "9 Best Midjourney Alternatives",
        "The best AI image generators",
    ]
    assert citations == [
        "https://www.imagine.art/blogs/midjourney-alternatives",
        "https://zapier.com/blog/best-ai-image-generator/",
    ]


def test_citations_alone_still_produce_sources():
    """Older/other responses may carry only the flat URL list. A URL must never
    be dropped just because the richer field was absent."""
    payload = {k: v for k, v in SONAR_RESPONSE.items() if k != "search_results"}
    sources, citations = _extract_sources(payload)

    assert len(sources) == 2
    assert all(s.title is None for s in sources)
    assert len(citations) == 2


def test_search_results_alone_backfill_the_citation_list():
    payload = {k: v for k, v in SONAR_RESPONSE.items() if k != "citations"}
    sources, citations = _extract_sources(payload)
    assert len(sources) == 2
    assert citations == [s.url for s in sources]


def test_ungrounded_providers_are_unaffected():
    """This adapter also serves Groq, OpenRouter, DeepSeek and Moonshot, none of
    which return either field. They must come back empty, not raise."""
    sources, citations = _extract_sources(
        {"choices": [{"message": {"content": "hi"}}], "usage": {}}
    )
    assert sources == []
    assert citations == []


@pytest.mark.parametrize(
    "payload",
    [
        {"search_results": "not-a-list"},
        {"search_results": [None, 3, "x"]},
        {"search_results": [{"title": "no url here"}]},
        {"citations": "not-a-list"},
        {"citations": [None, 7]},
    ],
)
def test_malformed_source_fields_do_not_raise(payload):
    """A provider that changes shape must degrade to 'no citations', never take
    down a scan that has already been paid for."""
    sources, citations = _extract_sources(payload)
    assert sources == []
    assert citations == []


def _provider_call(monkeypatch, response: dict[str, Any]):
    """Drive generate() with a stubbed HTTP layer."""

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return response

    monkeypatch.setattr(
        "app.gateway.providers.openai_compatible.post_with_retry",
        lambda *a, **k: _Resp(),
    )
    monkeypatch.setattr(
        "app.gateway.providers.openai_compatible.resolve_api_key",
        lambda env: "sk-test",
    )
    config = get_models_config()
    provider = OpenAICompatibleProvider.from_config(config)
    target = config.resolve("measurement_perplexity", "prod")
    return provider.generate(target, [Message(role="user", content="q")], {})


def test_generate_surfaces_sources_and_usage(monkeypatch):
    result = _provider_call(monkeypatch, SONAR_RESPONSE)

    assert result.text.startswith("The leading options")
    assert result.usage.total_tokens == 42
    assert len(result.sources) == 2
    assert result.sources[0].title == "9 Best Midjourney Alternatives"
    assert result.finish_reason == "stop"
    assert result.truncated is False


def test_a_cut_off_answer_is_marked_truncated(monkeypatch):
    """finish_reason='length' means the answer was cut off. The monitor refuses
    to build a mentioned=False observation on a truncated answer, so losing this
    flag would silently record 'brand absent' from an answer that never
    finished — the same defect the Gemini adapter already guards against."""
    cut_off = {
        **SONAR_RESPONSE,
        "choices": [
            {
                "index": 0,
                "finish_reason": "length",
                "message": {"role": "assistant", "content": "The leading options are"},
            }
        ],
    }
    result = _provider_call(monkeypatch, cut_off)

    assert result.finish_reason == "length"
    assert result.truncated is True


def test_sonar_is_priced_with_its_per_request_search_fee():
    """Sonar bills tokens PLUS a per-request fee for retrieval. Pricing it on
    tokens alone would under-report every measurement call."""
    from decimal import Decimal

    from app.gateway.cost import compute_cost
    from app.gateway.types import Usage

    target = get_models_config().resolve("measurement_perplexity", "prod")
    assert target.grounding is True
    assert target.price.grounded_request > 0

    grounded = compute_cost(target.price, Usage(prompt_tokens=1000), grounded=True)
    ungrounded = compute_cost(target.price, Usage(prompt_tokens=1000), grounded=False)
    # compute_cost works in Decimal; compare in Decimal rather than coercing to
    # float, so the assertion is exact and not tolerance-dependent.
    assert grounded - ungrounded == Decimal(str(target.price.grounded_request))

    # ...and it must be cheaper per grounded request than Gemini 2.5, which is
    # the entire reason to prefer it as the default engine.
    gemini = get_models_config().pricing["gemini/gemini-2.5-flash"]
    assert target.price.grounded_request < gemini.grounded_request
