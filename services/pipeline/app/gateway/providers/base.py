# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Provider abstraction.

A provider turns (target, messages, params) into raw text + token usage. Pricing,
caching, rate limiting, cost logging, and fallback are the gateway's job, not the
provider's — keeping providers thin and swappable.

Adding an engine is a new adapter file decorated with `@register_provider("name")`
(see registry.py) — the gateway discovers it, nothing there changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from app.gateway.models_config import ResolvedTarget
from app.gateway.types import Message, ProviderResult

if TYPE_CHECKING:
    from app.gateway.models_config import ModelsConfig


class Provider(ABC):
    @abstractmethod
    def generate(
        self,
        target: ResolvedTarget,
        messages: list[Message],
        params: dict[str, Any],
    ) -> ProviderResult:
        """Run one completion. Raises on unrecoverable error."""
        raise NotImplementedError

    @classmethod
    def from_config(cls, config: ModelsConfig) -> Provider:
        """Build an instance from the models config. The registry calls this, so
        every adapter is constructed the same way regardless of what it needs.
        Default: no-arg construction; adapters that need e.g. the retry policy
        override this (see the HTTP adapters)."""
        return cls()
