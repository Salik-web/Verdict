"""Per-provider rate limiting: a token bucket for the ceiling, plus optional
hard SPACING between calls. In-memory for now, behind an interface so a
Redis/distributed limiter can replace it later.

Two knobs, because they solve different problems:

* `rpm` — the sustained ceiling, as a token bucket. The bucket starts FULL, so it
  permits an instant burst of up to `rpm` calls. That's fine for a paid tier.
* `min_interval_s` — a floor on the gap between consecutive calls to a provider.
  Free tiers 429 on exactly the burst the bucket allows, so this is what makes a
  free tier survivable. It's enforced first.

Providers with neither configured (e.g. mock) are never throttled.
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
    def __init__(self, rpm: int | None, min_interval_s: float | None) -> None:
        self.rpm = rpm
        self.capacity = float(rpm) if rpm else 0.0
        self.tokens = float(rpm) if rpm else 0.0
        self.refill_per_s = (rpm / 60.0) if rpm else 0.0
        self.min_interval_s = min_interval_s or 0.0
        self.updated = time.monotonic()
        self.last_call: float | None = None
        self.lock = threading.Lock()


class TokenBucketRateLimiter(RateLimiter):
    def __init__(
        self,
        rpm_by_provider: dict[str, int | None],
        min_interval_by_provider: dict[str, float | None] | None = None,
    ) -> None:
        spacing = min_interval_by_provider or {}
        names = set(rpm_by_provider) | set(spacing)
        self._buckets = {
            name: _Bucket(rpm_by_provider.get(name), spacing.get(name))
            for name in names
            if rpm_by_provider.get(name) or spacing.get(name)
        }

    def acquire(self, provider: str) -> None:
        bucket = self._buckets.get(provider)
        if bucket is None:
            return
        self._space(bucket)
        self._take_token(bucket)

    def _space(self, bucket: _Bucket) -> None:
        """Sleep until at least min_interval_s has passed since the last call."""
        if bucket.min_interval_s <= 0:
            return
        while True:
            with bucket.lock:
                now = time.monotonic()
                if bucket.last_call is None:
                    bucket.last_call = now
                    return
                elapsed = now - bucket.last_call
                if elapsed >= bucket.min_interval_s:
                    bucket.last_call = now
                    return
                wait_s = bucket.min_interval_s - elapsed
            time.sleep(min(wait_s, 1.0))

    def _take_token(self, bucket: _Bucket) -> None:
        if not bucket.rpm:
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
