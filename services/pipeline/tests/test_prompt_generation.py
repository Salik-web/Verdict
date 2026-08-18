# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Prompt auto-generation, end to end against the DB (A4).

A fresh account starts with zero prompts and a scan with no prompts measures
nothing, so this is the path a new user hits first. What it has to guarantee:

  * calling it produces stored, active prompts;
  * calling it TWICE does not duplicate them — the endpoint is idempotent enough
    to be safe to retry from a UI;
  * a deployment with no generation key gets a named env var, not a stack trace.

Requires the migrated + seeded DB; skips cleanly if unreachable.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import OperationalError

from app.db.base import SessionLocal
from app.db.models import Account
from app.db.repositories import PromptRepository
from app.gateway.cost import NullCostSink
from app.gateway.gateway import build_gateway
from app.gateway.models_config import get_models_config
from app.pipeline.monitor.prompt_runner import (
    PromptGenerationUnavailable,
    generate_and_store_prompts,
)


def _db_ready() -> bool:
    try:
        with SessionLocal() as s:
            s.connection()
        return True
    except OperationalError:
        return False


def _gateway(mode: str = "mock"):
    return build_gateway(
        mode=mode, cost_sink=NullCostSink(), config=get_models_config()
    )


@pytest.fixture
def fresh_account():
    """A throwaway account, so assertions about prompt COUNTS are exact rather
    than dependent on whatever the dev database accumulated."""
    if not _db_ready():
        pytest.skip("database unreachable — run docker compose up + db:migrate")
    slug = f"promptgen-{uuid.uuid4().hex[:10]}"
    with SessionLocal() as s:
        account = Account(name="Prompt Gen Test", slug=slug, brand_name="Acme")
        s.add(account)
        s.commit()
        account_id = account.id
    yield account_id
    with SessionLocal() as s:
        s.query(Account).filter(Account.id == account_id).delete()
        s.commit()


def test_generates_and_stores_prompts(fresh_account):
    result = generate_and_store_prompts(fresh_account, gateway=_gateway())

    assert result["generated"] > 0
    assert result["created"] == result["generated"]
    assert result["skipped_duplicates"] == 0
    assert len(result["prompts"]) == result["created"]

    with SessionLocal() as s:
        stored = PromptRepository(s).list_by_account(fresh_account, active_only=True)
    assert len(stored) == result["created"]
    # Tagged so a UI can tell auto-generated prompts from hand-written ones.
    assert all(p.prompt_group == "auto" for p in stored)
    assert all(p.text.strip() for p in stored)


def test_running_twice_does_not_duplicate(fresh_account):
    """Safe to retry: the same pack asked for twice must not double the account's
    prompts, because a UI retry after a timeout is the normal case."""
    first = generate_and_store_prompts(fresh_account, gateway=_gateway())
    second = generate_and_store_prompts(fresh_account, gateway=_gateway())

    assert second["created"] == 0
    assert second["skipped_duplicates"] == second["generated"]

    with SessionLocal() as s:
        stored = PromptRepository(s).list_by_account(fresh_account)
    assert len(stored) == first["created"]


def test_deduplication_ignores_case_and_whitespace(fresh_account):
    """A hand-written prompt that differs only in spacing must still block its
    generated twin — otherwise the account slowly fills with near-duplicates."""
    generated = generate_and_store_prompts(fresh_account, gateway=_gateway())
    sample = generated["prompts"][0]["text"]

    with SessionLocal() as s:
        PromptRepository(s).create_many(
            fresh_account, [f"  {sample.upper()}  "], prompt_group="manual"
        )
        s.commit()

    again = generate_and_store_prompts(fresh_account, gateway=_gateway())
    assert again["created"] == 0


def test_missing_generation_key_names_the_env_var(fresh_account, monkeypatch):
    """The failure a self-hoster with no OpenRouter key actually hits."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    class _NoKeys:
        deployment_mode = "self_hosted"

    monkeypatch.setattr("app.gateway.credentials.get_settings", lambda: _NoKeys())

    with pytest.raises(PromptGenerationUnavailable) as exc:
        generate_and_store_prompts(fresh_account, gateway=_gateway("dev"))
    assert "OPENROUTER_API_KEY" in str(exc.value)


def test_unknown_account_is_a_value_error():
    if not _db_ready():
        pytest.skip("database unreachable")
    with pytest.raises(ValueError):
        generate_and_store_prompts(uuid.uuid4(), gateway=_gateway())
