# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Provider registry: a new adapter is a drop-in — the gateway never changes.

The decisive test is `test_new_adapter_dispatches_through_the_gateway`: it defines
a brand-new provider type, points a config at it, and shows a real Gateway routing
a call to it — without a single edit to gateway.py or a provider-type enum.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.gateway.cost import NullCostSink
from app.gateway.gateway import build_gateway
from app.gateway.models_config import ModelsConfig, ResolvedTarget
from app.gateway.providers import (
    Provider,
    build_providers,
    register_provider,
    registered_types,
)
from app.gateway.providers.registry import discover
from app.gateway.types import Message, ProviderResult, Usage


# A brand-new engine, registered the only way any engine is: a decorated class.
@register_provider("dummy_engine")
class DummyProvider(Provider):
    def generate(
        self, target: ResolvedTarget, messages: list[Message], params: dict[str, Any]
    ) -> ProviderResult:
        return ProviderResult(
            text=f"dummy:{target.model}",
            usage=Usage(prompt_tokens=1, completion_tokens=1),
            citations=["https://dummy.example/source"],
        )


def test_discovery_finds_the_real_adapters_on_disk():
    # No import list to maintain — the three shipped adapters are found by
    # scanning the package directory.
    types = registered_types()
    assert {"mock", "openai_compatible", "gemini"} <= set(types)


def test_build_providers_instantiates_every_registered_type():
    from app.gateway.models_config import get_models_config

    providers = build_providers(get_models_config())
    assert set(providers) >= {"mock", "openai_compatible", "gemini", "dummy_engine"}
    assert all(isinstance(p, Provider) for p in providers.values())


def test_new_adapter_dispatches_through_the_gateway():
    """The whole point: config references a type that didn't exist when gateway.py
    was written, and the gateway routes to it anyway. Zero gateway edits."""
    config = ModelsConfig.model_validate(
        {
            "default_mode": "dev",
            "tasks": {
                "measurement": {"dev": {"provider": "acme_llm", "model": "acme-1"}}
            },
            "providers": {"acme_llm": {"type": "dummy_engine"}},
        }
    )
    gw = build_gateway(mode="dev", cost_sink=NullCostSink(), config=config)

    res = gw.call(
        "measurement", [Message(role="user", content="hi")], account_id=uuid.uuid4()
    )

    assert res.text == "dummy:acme-1"
    assert res.provider == "acme_llm"
    # Citations flow back through the normalized boundary too.
    assert res.citations == ["https://dummy.example/source"]


def test_unknown_provider_type_fails_fast_and_lists_options():
    config = ModelsConfig.model_validate(
        {
            "default_mode": "dev",
            "tasks": {"measurement": {"dev": {"provider": "typo", "model": "x"}}},
            "providers": {"typo": {"type": "no_such_adapter"}},
        }
    )
    with pytest.raises(ValueError, match="no adapter registered") as exc:
        build_gateway(mode="dev", cost_sink=NullCostSink(), config=config)
    # The error names what IS available, so a typo is obvious.
    assert "gemini" in str(exc.value)


def test_double_registration_of_a_different_class_is_rejected():
    with pytest.raises(ValueError, match="already registered"):

        @register_provider("dummy_engine")
        class Clashing(Provider):
            def generate(self, target, messages, params):  # pragma: no cover
                raise NotImplementedError


def test_reregistering_the_same_class_is_idempotent():
    # discover() re-imports modules on some paths; a module re-registering its own
    # class must not explode.
    register_provider("dummy_engine")(DummyProvider)
    discover()  # idempotent, no raise
