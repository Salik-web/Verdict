# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""An answer we never received is not an answer in which the brand was absent.

Audit finding #3: two of ten measurement calls came back with a candidate that
had no `parts`. The provider returned text="" and success, so both were stored as
real observations with mentioned=False — every mention_rate was divided by 10
when only 8 answers existed, understating visibility by ~20%. `finishReason` was
never inspected, so after the fact the cause was unrecoverable.

This is the same confusion the diagnosis stage already fixed between
CHECK_FAILED and CONFIRMED_ABSENT, one stage upstream.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.gateway.models_config import ProviderConfig, ResolvedTarget, RetryConfig
from app.gateway.providers import gemini as gemini_mod
from app.gateway.providers.gemini import EmptyCandidate, GeminiProvider
from app.gateway.types import Message
from app.pipeline.contracts import CompetitorRef, PromptRef, ScanContext
from app.pipeline.monitor.config import EngineConfig
from app.pipeline.monitor.graph import build_monitor_graph


def _target(**over) -> ResolvedTarget:
    base: dict[str, Any] = dict(
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
        price=None,
    )
    base.update(over)
    return ResolvedTarget(**base)


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


@pytest.fixture
def respond(monkeypatch):
    """Stub the HTTP layer with a chosen Gemini payload; hand back what we sent."""
    sent: dict[str, Any] = {}
    reply: dict[str, Any] = {}

    def _post(url, *, headers, payload, retry, timeout_s, provider, model):
        sent["payload"] = payload
        return _FakeResponse(reply["body"])

    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setattr(gemini_mod, "post_with_retry", _post)

    def _install(body: dict[str, Any]) -> dict[str, Any]:
        reply["body"] = body
        return sent

    return _install


# ── provider level ───────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "candidate, expect_reason",
    [
        # The exact shape observed in scan 4ca73df6: 200 OK, a candidate, no parts.
        ({"content": {"role": "model"}, "finishReason": "MAX_TOKENS"}, "MAX_TOKENS"),
        ({"content": {"parts": []}, "finishReason": "SAFETY"}, "SAFETY"),
        ({"content": {"parts": [{"text": "   "}]}, "finishReason": "STOP"}, "STOP"),
    ],
)
def test_empty_candidate_raises_instead_of_returning_an_empty_answer(
    respond, candidate, expect_reason
):
    respond(
        {
            "candidates": [candidate],
            "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 29},
        }
    )
    with pytest.raises(EmptyCandidate) as err:
        GeminiProvider(RetryConfig()).generate(
            _target(), [Message(role="user", content="hi")], {}
        )
    # finishReason must survive: without it "we got nothing" is indistinguishable
    # from "it said nothing relevant" once the response is gone.
    assert err.value.finish_reason == expect_reason
    assert expect_reason in str(err.value)


def test_truncated_answer_is_flagged_but_still_returned(respond):
    respond(
        {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Midjourney is a lead"}]},
                    "finishReason": "MAX_TOKENS",
                }
            ],
            "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 5},
        }
    )
    result = GeminiProvider(RetryConfig()).generate(
        _target(), [Message(role="user", content="hi")], {}
    )
    assert result.text == "Midjourney is a lead"
    assert result.truncated is True
    assert result.finish_reason == "MAX_TOKENS"


def test_complete_answer_is_not_flagged(respond):
    respond(
        {
            "candidates": [
                {
                    "content": {"parts": [{"text": "full answer"}]},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {},
        }
    )
    result = GeminiProvider(RetryConfig()).generate(
        _target(), [Message(role="user", content="hi")], {}
    )
    assert result.truncated is False
    assert result.finish_reason == "STOP"


def test_thinking_budget_is_sent_when_configured(respond):
    """Thinking tokens are what exhaust maxOutputTokens and produce the empty
    candidate above; processing sets 0 so it cannot happen there."""
    sent = respond(
        {
            "candidates": [
                {"content": {"parts": [{"text": "{}"}]}, "finishReason": "STOP"}
            ],
            "usageMetadata": {},
        }
    )
    GeminiProvider(RetryConfig()).generate(
        _target(task="processing", json_output=True, thinking_budget=0),
        [Message(role="user", content="hi")],
        {},
    )
    assert sent["payload"]["generationConfig"]["thinkingConfig"] == {
        "thinkingBudget": 0
    }


def test_thinking_config_is_omitted_when_unset(respond):
    sent = respond(
        {
            "candidates": [
                {"content": {"parts": [{"text": "x"}]}, "finishReason": "STOP"}
            ],
            "usageMetadata": {},
        }
    )
    GeminiProvider(RetryConfig()).generate(
        _target(), [Message(role="user", content="hi")], {}
    )
    assert "thinkingConfig" not in sent["payload"].get("generationConfig", {})


# ── stage level: the denominator ─────────────────────────────────────────
class _StubGateway:
    """Answers `answers` in order; a None entry raises like an empty candidate."""

    mode = "dev"

    def __init__(self, answers: list[str | None], truncated: set[int] = frozenset()):
        self._answers = answers
        self._truncated = truncated
        self._i = 0

    def call(self, task, messages, **kw):
        from app.gateway.types import GatewayResponse, Usage

        if task == "processing":
            return GatewayResponse(
                text='{"brand":"Acme","mentioned":true,"competitors":['
                '{"brand":"Globex"}]}',
                usage=Usage(),
                model="m",
                provider="p",
                mode="dev",
            )
        i = self._i
        self._i += 1
        text = self._answers[i]
        if text is None:
            raise EmptyCandidate("no parts", finish_reason="MAX_TOKENS")
        return GatewayResponse(
            text=text,
            usage=Usage(),
            model="m",
            provider="p",
            mode="dev",
            finish_reason="MAX_TOKENS" if i in self._truncated else "STOP",
            truncated=i in self._truncated,
        )


def _context(repeats: int) -> ScanContext:
    return ScanContext(
        scan_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        brand_name="Acme",
        competitors=[CompetitorRef(id=uuid.uuid4(), name="Globex")],
        prompts=[PromptRef(id=uuid.uuid4(), text="best crm")],
        engines=["primary"],
        repeats=repeats,
    )


def _run(gateway, context):
    graph = build_monitor_graph(gateway, [EngineConfig(name="primary")])
    return graph.invoke({"context": context})


ANSWER = "Acme and Globex are the leaders."


def test_failed_observations_leave_the_denominator():
    # 5 runs: 2 come back empty. Only 3 real answers exist.
    gw = _StubGateway([ANSWER, None, ANSWER, None, ANSWER])
    final = _run(gw, _context(5))

    assert len(final["failed_observations"]) == 2
    assert {f.finish_reason for f in final["failed_observations"]} == {"MAX_TOKENS"}

    rows = {r.brand: r for r in final["share_of_voice"] if r.engine == "all"}
    # THE bug: observations must be 3, not 5. At 5 the rate would read 0.6.
    assert rows["Acme"].details["observations"] == 3
    assert rows["Acme"].mention_rate == 1.0
    assert rows["Acme"].mention_count == 3


def test_an_empty_answer_never_becomes_a_mentioned_false_row():
    gw = _StubGateway([None, None, None, None, None])
    final = _run(gw, _context(5))
    # Nothing was measured, so there is nothing to report — NOT a table of
    # confident 0%s that would read to a customer as "you are invisible".
    assert final["mentions"] == []
    assert final["share_of_voice"] == []
    assert len(final["failed_observations"]) == 5


def test_truncated_answers_are_excluded_too():
    gw = _StubGateway([ANSWER] * 4, truncated={1, 3})
    final = _run(gw, _context(4))
    assert [f.reason for f in final["failed_observations"]] == [
        "answer truncated before completion"
    ] * 2
    rows = {r.brand: r for r in final["share_of_voice"] if r.engine == "all"}
    assert rows["Acme"].details["observations"] == 2


def test_one_refused_call_does_not_void_the_whole_scan():
    gw = _StubGateway([None, ANSWER, ANSWER, ANSWER, ANSWER])
    final = _run(gw, _context(5))
    assert len(final["mentions"]) == 8  # 4 answers x (target + 1 competitor)
    assert len(final["failed_observations"]) == 1
