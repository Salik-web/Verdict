# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""BYOK: key resolution is a deployment mode, and a missing key is a STATE.

Two properties this pins, both of which a self-hosting user depends on:

1. `self_hosted` reads the operator's keys from the environment; `managed`
   asks an injected per-tenant lookup, scoped to the account the gateway is
   currently calling for. Same code, one env var apart.
2. An engine whose key is absent is reported as unavailable and skipped — a user
   with one key gets a working one-engine scan, not a crash and not a bill for
   the engines that happened to work before the failure.
"""

from __future__ import annotations

import uuid

import pytest

from app.gateway.availability import all_task_statuses, task_status
from app.gateway.cost import NullCostSink
from app.gateway.credentials import (
    AccountCredentialResolver,
    EnvCredentialResolver,
    account_scope,
    current_account,
    get_credential_resolver,
    resolve_api_key,
    set_credential_resolver,
)
from app.gateway.gateway import build_gateway
from app.gateway.models_config import get_models_config
from app.gateway.types import Message
from app.pipeline.monitor.config import EngineConfig
from app.pipeline.monitor.stage import NoEngineAvailable, available_engines

ACCOUNT_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
ACCOUNT_B = uuid.UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture(autouse=True)
def _clean_resolver():
    set_credential_resolver(None)
    yield
    set_credential_resolver(None)


# ── self_hosted: operator keys from the environment ──────────────────────
def test_env_resolver_reads_the_process_environment(monkeypatch):
    monkeypatch.setenv("GEO_TEST_KEY", "sk-from-env")
    assert EnvCredentialResolver().resolve("GEO_TEST_KEY") == "sk-from-env"


def test_env_resolver_falls_back_to_dotenv_backed_settings(monkeypatch):
    """A key that lives only in .env is NOT in os.environ. Reading os.environ
    alone is the bug this fallback exists to prevent."""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    from app.core import config as config_module

    class _FakeSettings:
        google_api_key = "sk-from-dotenv"
        deployment_mode = "self_hosted"

    monkeypatch.setattr(config_module, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.gateway.credentials.get_settings", lambda: _FakeSettings())
    assert EnvCredentialResolver().resolve("GOOGLE_API_KEY") == "sk-from-dotenv"


def test_missing_key_is_none_not_an_exception(monkeypatch):
    monkeypatch.delenv("GEO_ABSENT_KEY", raising=False)
    assert EnvCredentialResolver().resolve("GEO_ABSENT_KEY") is None


def test_default_deployment_is_self_hosted():
    assert isinstance(get_credential_resolver(), EnvCredentialResolver)


# ── managed: per-tenant keys from an injected lookup ─────────────────────
def test_managed_resolver_returns_the_scoped_accounts_key():
    keys = {
        (ACCOUNT_A, "OPENAI_API_KEY"): "sk-a",
        (ACCOUNT_B, "OPENAI_API_KEY"): "sk-b",
    }
    set_credential_resolver(
        AccountCredentialResolver(lambda acc, env: keys.get((acc, env)))
    )
    with account_scope(ACCOUNT_A):
        assert resolve_api_key("OPENAI_API_KEY") == "sk-a"
    with account_scope(ACCOUNT_B):
        assert resolve_api_key("OPENAI_API_KEY") == "sk-b"


def test_managed_resolver_can_refuse_to_fall_back_to_operator_keys(monkeypatch):
    """A tenant with no key of its own must not silently spend the operator's."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-operator")
    set_credential_resolver(
        AccountCredentialResolver(lambda acc, env: None, fallback_to_env=False)
    )
    with account_scope(ACCOUNT_A):
        assert resolve_api_key("OPENAI_API_KEY") is None

    set_credential_resolver(
        AccountCredentialResolver(lambda acc, env: None, fallback_to_env=True)
    )
    with account_scope(ACCOUNT_A):
        assert resolve_api_key("OPENAI_API_KEY") == "sk-operator"


def test_account_scope_is_restored_and_does_not_leak():
    assert current_account() is None
    with account_scope(ACCOUNT_A):
        assert current_account() == ACCOUNT_A
        with account_scope(ACCOUNT_B):
            assert current_account() == ACCOUNT_B
        assert current_account() == ACCOUNT_A
    assert current_account() is None


def test_gateway_binds_the_account_for_the_duration_of_the_call():
    """The contextvar must be set by the GATEWAY, not by each adapter — that is
    what lets a managed deployment resolve per-tenant keys without every
    third-party adapter having to know about tenancy.

    Asserted from INSIDE a provider, because "the adapter sees the right tenant
    while it is running" is the actual guarantee; checking the contextvar around
    the call would pass even if the gateway never set it.
    """
    from app.gateway.gateway import Gateway
    from app.gateway.providers.base import Provider
    from app.gateway.types import ProviderResult, Usage

    seen: list[uuid.UUID | None] = []

    class RecordingProvider(Provider):
        def generate(self, target, messages, params):
            seen.append(current_account())
            return ProviderResult(text="ok", usage=Usage())

    gw = Gateway(
        mode="mock",
        config=get_models_config(),
        providers={"mock": RecordingProvider()},
        cost_sink=NullCostSink(),
    )

    with account_scope(ACCOUNT_A):
        gw.call(
            "measurement", [Message(role="user", content="hi")], account_id=ACCOUNT_B
        )
        # Restored to the OUTER scope, not left on the call's account.
        assert current_account() == ACCOUNT_A

    # The provider saw the account the call was made FOR, not the ambient one.
    assert seen == [ACCOUNT_B]


# ── availability: a missing key is a state, not a crash ──────────────────
def test_mock_mode_needs_no_key():
    for status in all_task_statuses("mock"):
        assert status.available, status.reason


def test_task_is_unavailable_when_its_key_is_missing(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    class _NoKeys:
        deployment_mode = "self_hosted"

    monkeypatch.setattr("app.gateway.credentials.get_settings", lambda: _NoKeys())

    status = task_status("measurement", "dev")
    assert status.available is False
    assert status.missing_key_env == "GOOGLE_API_KEY"
    # The reason must tell the operator what to actually do.
    assert "GOOGLE_API_KEY" in status.reason
    assert "is not set" in status.reason


def test_available_engines_partitions_rather_than_raising(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    class _NoKeys:
        deployment_mode = "self_hosted"

    monkeypatch.setattr("app.gateway.credentials.get_settings", lambda: _NoKeys())

    gw = build_gateway(mode="dev", cost_sink=NullCostSink(), config=get_models_config())
    engines = [EngineConfig(name="primary", gateway_task="measurement")]
    usable, unavailable = available_engines(engines, gw)

    assert usable == []
    assert len(unavailable) == 1
    assert "GOOGLE_API_KEY" in unavailable[0]


def test_no_engine_available_names_what_to_set(monkeypatch):
    """The failure a misconfigured self-hoster actually hits. It must name the
    env var, not say 'measurement failed'."""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    class _NoKeys:
        deployment_mode = "self_hosted"

    monkeypatch.setattr("app.gateway.credentials.get_settings", lambda: _NoKeys())

    import uuid as _uuid

    from app.pipeline.contracts import PromptRef, ScanContext
    from app.pipeline.monitor.stage import run_monitor

    gw = build_gateway(mode="dev", cost_sink=NullCostSink(), config=get_models_config())
    ctx = ScanContext(
        scan_id=_uuid.uuid4(),
        account_id=ACCOUNT_A,
        brand_name="Acme",
        competitors=[],
        prompts=[PromptRef(id=_uuid.uuid4(), text="best tool?")],
        engines=["primary"],
        repeats=1,
    )
    with pytest.raises(NoEngineAvailable) as exc:
        run_monitor(ctx, gw)
    assert "GOOGLE_API_KEY" in str(exc.value)
