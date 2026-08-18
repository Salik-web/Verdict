# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Mock fixture labels must not leak into dev/prod cache keys.

Audit finding #6. `mock_scenarios` in monitor.yaml exists to cycle canned fixture
responses so repeated mock runs vary. The label is also part of the gateway's
cache key — correctly, since two mock calls with different fixtures are different
calls. But it was emitted in EVERY mode, so in dev two byte-identical `processing`
prompts hashed differently ("competitor_wins" vs "customer_invisible") and both
were billed instead of the second hitting the cache.

Visible in scan 4ca73df6: the two parse calls for the two empty answers were the
same 429-token prompt and both paid.
"""

from __future__ import annotations

from app.gateway.cache import cache_key
from app.gateway.types import Message
from app.pipeline.monitor.config import EngineConfig

ENGINE = EngineConfig(
    name="primary",
    mock_scenarios=["competitor_wins", "competitor_wins", "customer_invisible"],
)


def test_mock_mode_still_cycles_scenarios():
    labels = [ENGINE.scenario_for_run(i, "mock") for i in range(4)]
    assert labels == [
        "competitor_wins",
        "competitor_wins",
        "customer_invisible",
        "competitor_wins",
    ]


def test_dev_and_prod_emit_no_scenario():
    assert ENGINE.scenario_for_run(0, "dev") is None
    assert ENGINE.scenario_for_run(2, "dev") is None
    assert ENGINE.scenario_for_run(2, "prod") is None


def test_default_is_mock_so_existing_callers_are_unchanged():
    assert ENGINE.scenario_for_run(0) == "competitor_wins"


def test_an_engine_without_fixtures_never_emits_one():
    assert EngineConfig(name="primary").scenario_for_run(0, "mock") is None


def test_identical_dev_prompts_now_share_a_cache_key():
    """The consequence: the same prompt on two different runs is one billable
    call, not two."""
    msgs = [Message(role="user", content="extract brands from: ...")]
    keys = {
        cache_key(
            task="processing",
            mode="dev",
            provider="gemini",
            model="gemini-3.1-flash-lite",
            scenario=ENGINE.scenario_for_run(run, "dev"),
            messages=msgs,
            params={},
        )
        for run in range(5)
    }
    assert len(keys) == 1


def test_mock_scenarios_still_produce_distinct_keys():
    """The labels must keep working where they mean something — two different
    fixtures are genuinely two different calls."""
    msgs = [Message(role="user", content="same prompt")]
    keys = {
        cache_key(
            task="measurement",
            mode="mock",
            provider="mock",
            model="sonar",
            scenario=ENGINE.scenario_for_run(run, "mock"),
            messages=msgs,
            params={},
        )
        for run in range(3)
    }
    assert len(keys) == 2  # competitor_wins, customer_invisible
