"""Provider abstraction.

A provider turns (target, messages, params) into raw text + token usage. Pricing,
caching, rate limiting, cost logging, and fallback are the gateway's job, not the
provider's — keeping providers thin and swappable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.gateway.models_config import ResolvedTarget
from app.gateway.types import Message, ProviderResult


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
