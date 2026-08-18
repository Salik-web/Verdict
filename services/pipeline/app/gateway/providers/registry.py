# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Provider registry — zero-touch adapter registration.

Adding an engine is exactly: drop a file in this package, decorate its class with
`@register_provider("<type>")`. That's it. The gateway never changes: `build_gateway`
calls `build_providers(config)`, which auto-imports every module in this package
(running the decorators) and constructs one instance per registered type via
`Provider.from_config`.

The `type` string is the registry key AND the value used in
config/models.yaml (`providers.<name>.type`). There is no provider-type enum to
edit — validity is "is it registered?", checked with a helpful error at gateway
build (see `ensure_registered`).
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from typing import TYPE_CHECKING

from app.gateway.providers.base import Provider

if TYPE_CHECKING:
    from app.gateway.models_config import ModelsConfig

# Modules in this package that are NOT adapters (no @register_provider).
_NON_ADAPTER_MODULES = {"base", "http", "registry"}

_REGISTRY: dict[str, type[Provider]] = {}
_discovered = False


def register_provider(name: str) -> Callable[[type[Provider]], type[Provider]]:
    """Class decorator: register an adapter under a `type` name."""

    def decorate(cls: type[Provider]) -> type[Provider]:
        existing = _REGISTRY.get(name)
        if existing is not None and existing is not cls:
            raise ValueError(
                f"provider type '{name}' is already registered by "
                f"{existing.__name__}; pick a distinct name for {cls.__name__}"
            )
        _REGISTRY[name] = cls
        return cls

    return decorate


def discover() -> None:
    """Import every adapter module in this package so its decorator runs.

    This is what makes registration zero-touch: a new adapter file is found on
    disk, no import list to append. Idempotent.
    """
    global _discovered
    if _discovered:
        return
    import app.gateway.providers as package

    for module in pkgutil.iter_modules(package.__path__):
        if module.name not in _NON_ADAPTER_MODULES:
            importlib.import_module(f"{package.__name__}.{module.name}")
    _discovered = True


def registered_types() -> list[str]:
    discover()
    return sorted(_REGISTRY)


def ensure_registered(names: list[str]) -> None:
    """Raise if any referenced provider type has no adapter — a config typo or a
    missing file surfaces here with the list of what's available, not as an
    obscure failure at first call."""
    discover()
    unknown = [n for n in names if n not in _REGISTRY]
    if unknown:
        raise ValueError(
            f"no adapter registered for provider type(s) {unknown}; "
            f"available: {sorted(_REGISTRY)}. Add an adapter file decorated with "
            f"@register_provider(...) in app/gateway/providers/."
        )


def build_providers(config: ModelsConfig) -> dict[str, Provider]:
    """One instance per registered adapter, built via `from_config`."""
    discover()
    return {name: cls.from_config(config) for name, cls in _REGISTRY.items()}
