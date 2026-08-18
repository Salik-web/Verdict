# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Generator registry: fix_type -> Generator. This is the extension point.

**This distribution ships zero generators.** Planning still runs, ranks gaps and
emits a backlog; a fix_type with no registered generator is reported as an
advisory backlog item (see stage.py), never a crash. That is the same path the
already-advisory fix types (`remove_noindex`, `add_freshness_signals`) have
always taken — it is now simply the general case rather than a special case.

Three ways to add generators, none of which require forking this repo:

1. **Entry point (recommended for a separate package).** A distribution declares

       [project.entry-points."geo.generators"]
       comparison_page = "mypkg.generators:ComparisonPageGenerator"

   and `build_registry()` discovers it on import. The value may be a Generator
   subclass, or a factory callable returning a Generator or a list of them.
   Anything taking a single parameter is handed the Gateway.

2. **In-process registration.** `register_generator(MyGenerator())` — useful for
   an application that composes this package directly, and for tests.

3. **Explicit injection.** `ExecutionStage(registry={...})` bypasses discovery
   entirely; the stage never reaches for a global.

A generator that fails to load is skipped with a warning rather than taking the
pipeline down: a broken third-party plugin must not stop monitoring/diagnosis.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from importlib.metadata import entry_points
from typing import Any

from app.gateway import Gateway
from app.pipeline.execution.base import Generator

log = logging.getLogger(__name__)

#: setuptools/PEP 621 entry-point group scanned for third-party generators.
GENERATOR_ENTRY_POINT_GROUP = "geo.generators"

#: Generators registered in-process via `register_generator`.
_REGISTERED: list[Generator] = []


def register_generator(generator: Generator) -> None:
    """Register a generator for this process. Last registration for a fix_type
    wins, so an application can deliberately override a plugin's."""
    _REGISTERED.append(generator)


def clear_generators() -> None:
    """Drop all in-process registrations (tests, and re-composition)."""
    _REGISTERED.clear()


def registered_generators() -> list[Generator]:
    return list(_REGISTERED)


def _instantiate(loaded: Any, gateway: Gateway | None) -> Iterable[Generator]:
    """Turn an entry-point value into Generator instances.

    Accepts a Generator instance, a Generator subclass, or a factory. Anything
    callable that declares a single parameter is given the Gateway — generators
    that call a model need it; deterministic ones do not.
    """
    if isinstance(loaded, Generator):
        return [loaded]

    obj: Callable[..., Any] = loaded
    try:
        import inspect

        params = [
            p
            for p in inspect.signature(obj).parameters.values()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
        ]
        required = [p for p in params if p.default is p.empty]
        result = obj(gateway) if len(required) == 1 else obj()
    except TypeError:
        result = obj()

    if isinstance(result, Generator):
        return [result]
    if isinstance(result, Iterable):
        return [g for g in result if isinstance(g, Generator)]
    return []


def discover_generators(gateway: Gateway | None = None) -> list[Generator]:
    """Load every generator advertised on the `geo.generators` entry point."""
    found: list[Generator] = []
    try:
        points = entry_points(group=GENERATOR_ENTRY_POINT_GROUP)
    except Exception:  # pragma: no cover - importlib backport differences
        return found

    for point in points:
        try:
            found.extend(_instantiate(point.load(), gateway))
        except Exception as exc:
            # A third-party plugin must never break the pipeline it plugs into.
            log.warning(
                "generator entry point %r failed to load: %s: %s",
                point.name,
                type(exc).__name__,
                exc,
            )
    return found


def build_registry(gateway: Gateway | None = None) -> dict[str, Generator]:
    """fix_type -> Generator for everything available to this process.

    Returns `{}` on a stock install. Discovery order is entry points first, then
    in-process registrations, so an application's explicit `register_generator`
    call overrides a plugin that claims the same fix_type.
    """
    registry: dict[str, Generator] = {}
    for generator in [*discover_generators(gateway), *_REGISTERED]:
        registry[generator.fix_type] = generator
    return registry
