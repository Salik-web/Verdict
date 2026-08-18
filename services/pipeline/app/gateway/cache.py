# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Response cache. In-memory + per-process for now, behind an interface so a
Redis-backed cache (shared across Celery workers) can drop in later.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from abc import ABC, abstractmethod
from typing import Any

from app.gateway.types import GatewayResponse, Message


def cache_key(
    *,
    task: str,
    mode: str,
    provider: str,
    model: str,
    scenario: str | None,
    messages: list[Message],
    params: dict[str, Any],
) -> str:
    payload = {
        "task": task,
        "mode": mode,
        "provider": provider,
        "model": model,
        "scenario": scenario,
        "messages": [m.model_dump() for m in messages],
        # Only generation params affect the response; context (account/job/scan)
        # and the scenario (already above) are excluded.
        "params": {
            k: params[k]
            for k in ("temperature", "max_tokens", "top_p", "response_format")
            if k in params
        },
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


class CacheBackend(ABC):
    @abstractmethod
    def get(self, key: str) -> GatewayResponse | None: ...

    @abstractmethod
    def set(self, key: str, value: GatewayResponse, ttl_s: int) -> None: ...


class InMemoryTTLCache(CacheBackend):
    def __init__(self) -> None:
        self._store: dict[str, tuple[float, GatewayResponse]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> GatewayResponse | None:
        with self._lock:
            hit = self._store.get(key)
            if not hit:
                return None
            expires_at, value = hit
            if expires_at < time.monotonic():
                self._store.pop(key, None)
                return None
            return value.model_copy(update={"cached": True})

    def set(self, key: str, value: GatewayResponse, ttl_s: int) -> None:
        with self._lock:
            self._store[key] = (time.monotonic() + ttl_s, value)
