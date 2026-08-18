# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Gateway checkpoint tests.

With NO API keys (mock mode, the default), a sample call for each task returns
realistic text and produces a cost entry. Swapping a model is config-only.
The DB-backed test proves a row actually lands in llm_cost_log.
"""

from __future__ import annotations

import copy
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.gateway.cost import NullCostSink
from app.gateway.gateway import build_gateway
from app.gateway.models_config import TaskTarget, get_models_config
from app.gateway.types import Message

DEMO_ACCOUNT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
MESSAGES = [Message(role="user", content="Best product analytics tool for B2B SaaS?")]

TASKS = {
    "measurement": "sonar",
    "processing": "deepseek-v4-flash",
    "generation": "kimi-k2.7",
}


@pytest.fixture
def mock_gateway():
    """Mock-mode gateway with an in-memory cost sink (no DB, no keys)."""
    sink = NullCostSink()
    gw = build_gateway(mode="mock", cost_sink=sink, config=get_models_config())
    return gw, sink


@pytest.mark.parametrize("task,expected_model", TASKS.items())
def test_each_task_returns_text_and_logs_cost(mock_gateway, task, expected_model):
    gw, sink = mock_gateway
    res = gw.call(task, MESSAGES, account_id=DEMO_ACCOUNT_ID)

    assert res.text.strip(), f"{task} returned empty text"
    assert res.model == expected_model  # comes from config/models.yaml
    assert res.usage.total_tokens > 0
    assert res.mode == "mock"

    assert len(sink.entries) == 1
    entry = sink.entries[0]
    assert entry.operation == task
    assert entry.mock is True
    assert entry.cost_usd >= 0


def test_scenarios_are_selectable(mock_gateway):
    gw, _ = mock_gateway
    wins = gw.call(
        "measurement", MESSAGES, account_id=DEMO_ACCOUNT_ID, scenario="competitor_wins"
    )
    invisible = gw.call(
        "measurement",
        MESSAGES,
        account_id=DEMO_ACCOUNT_ID,
        scenario="customer_invisible",
    )
    assert "Acme Analytics" in wins.text
    assert "Acme Analytics" not in invisible.text
    assert wins.text != invisible.text


def test_cache_hit_is_logged_flagged_cached_with_zero_cost(mock_gateway):
    """A cache hit spends nothing but is STILL a logical call — it must leave a
    row flagged cached (cost 0) so the ledger is complete for the pricing model."""
    gw, sink = mock_gateway
    first = gw.call("generation", MESSAGES, account_id=DEMO_ACCOUNT_ID)
    second = gw.call("generation", MESSAGES, account_id=DEMO_ACCOUNT_ID)
    assert first.cached is False
    assert second.cached is True

    assert len(sink.entries) == 2  # both calls logged
    assert sink.entries[0].cached is False
    hit = sink.entries[1]
    assert hit.cached is True
    assert hit.status == "ok"
    assert hit.cost_usd == 0


def test_measurement_is_never_cache_served(mock_gateway):
    """Repeats must be fresh samples: measurement is excluded from the cache, so
    two identical measurement calls both hit the provider and both get logged
    (this is the bug that made runs 2-5 identical and unlogged)."""
    gw, sink = mock_gateway
    a = gw.call(
        "measurement", MESSAGES, account_id=DEMO_ACCOUNT_ID, scenario="competitor_wins"
    )
    b = gw.call(
        "measurement", MESSAGES, account_id=DEMO_ACCOUNT_ID, scenario="competitor_wins"
    )
    assert a.cached is False and b.cached is False
    assert len(sink.entries) == 2
    assert all(e.cached is False for e in sink.entries)


def test_failed_call_is_logged_with_error_status():
    """A call that raises (after any fallback) still leaves a row — zero usage,
    status 'error' — so a missing row can only ever mean a logging bug."""
    from app.gateway.gateway import Gateway
    from app.gateway.models_config import ModelsConfig, ProviderConfig, TaskTarget

    class _BoomProvider:
        def generate(self, target, msgs, params):
            raise RuntimeError("kaboom")

    cfg = ModelsConfig(
        tasks={"processing": {"mock": TaskTarget(provider="boom", model="x")}},
        providers={"boom": ProviderConfig(type="boom")},
    )
    sink = NullCostSink()
    gw = Gateway(
        mode="mock",
        config=cfg,
        providers={"boom": _BoomProvider()},
        cost_sink=sink,
        cache=None,
    )
    with pytest.raises(RuntimeError):
        gw.call("processing", MESSAGES, account_id=DEMO_ACCOUNT_ID)

    assert len(sink.entries) == 1
    assert sink.entries[0].status == "error"
    assert sink.entries[0].cost_usd == 0


def test_model_swap_is_config_only(mock_gateway):
    """Flipping the model in config (no code change) changes the result."""
    _, sink = mock_gateway
    cfg = copy.deepcopy(get_models_config())
    cfg.tasks["measurement"]["mock"] = TaskTarget(
        provider="mock",
        model="kimi-k2.7",  # was "sonar"
        fixture_dir="measurement",
        default_scenario="competitor_wins",
    )
    gw = build_gateway(mode="mock", cost_sink=NullCostSink(), config=cfg)
    res = gw.call("measurement", MESSAGES, account_id=DEMO_ACCOUNT_ID)
    assert res.model == "kimi-k2.7"


def test_cost_row_written_to_db():
    """End-to-end: a mock call writes one row to llm_cost_log."""
    from app.db.base import SessionLocal
    from app.db.models import LlmCostLog

    try:
        with SessionLocal() as probe:
            probe.connection()
    except OperationalError:
        pytest.skip("database unreachable — run docker compose up + db:migrate/seed")

    def count() -> int:
        with SessionLocal() as s:
            return s.scalar(
                select(func.count())
                .select_from(LlmCostLog)
                .where(LlmCostLog.account_id == DEMO_ACCOUNT_ID)
            )

    before = count()
    gw = build_gateway(mode="mock", config=get_models_config())  # default DbCostSink
    res = gw.call(
        "measurement",
        MESSAGES,
        account_id=DEMO_ACCOUNT_ID,
        scenario="customer_invisible",
    )
    assert count() == before + 1
    assert res.cost_usd >= 0
