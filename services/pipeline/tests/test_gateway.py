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


def test_cache_returns_hit_without_new_cost(mock_gateway):
    gw, sink = mock_gateway
    first = gw.call("generation", MESSAGES, account_id=DEMO_ACCOUNT_ID)
    second = gw.call("generation", MESSAGES, account_id=DEMO_ACCOUNT_ID)
    assert first.cached is False
    assert second.cached is True
    assert len(sink.entries) == 1  # cache hit logged no extra cost row


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
