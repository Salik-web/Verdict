"""Per-provider rate limiting. In-memory token bucket for now, behind an
interface so a Redis/distributed limiter can replace it later.

Providers without a configured `rpm` (e.g. mock) are never throttled.
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod


class RateLimiter(ABC):
    @abstractmethod
    def acquire(self, provider: str) -> None:
        """Block until a request slot for `provider` is available."""


class NoopRateLimiter(RateLimiter):
    def acquire(self, provider: str) -> None:  # noqa: D401 - trivial
        return None


class _Bucket:
    def __init__(self, rpm: int) -> None:
        self.capacity = float(rpm)
        self.tokens = float(rpm)
        self.refill_per_s = rpm / 60.0
        self.updated = time.monotonic()
        self.lock = threading.Lock()


class TokenBucketRateLimiter(RateLimiter):
    def __init__(self, rpm_by_provider: dict[str, int]) -> None:
        self._buckets = {p: _Bucket(rpm) for p, rpm in rpm_by_provider.items() if rpm}

    def acquire(self, provider: str) -> None:
        bucket = self._buckets.get(provider)
        if bucket is None:
            return
        while True:
            with bucket.lock:
                now = time.monotonic()
                bucket.tokens = min(
                    bucket.capacity,
                    bucket.tokens + (now - bucket.updated) * bucket.refill_per_s,
                )
                bucket.updated = now
                if bucket.tokens >= 1.0:
                    bucket.tokens -= 1.0
                    return
                wait_s = (1.0 - bucket.tokens) / bucket.refill_per_s
            time.sleep(min(wait_s, 1.0))
