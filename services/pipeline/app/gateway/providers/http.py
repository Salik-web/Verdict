# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Shared HTTP plumbing for real (non-mock) providers: one retry/backoff policy.

Free tiers are the design point here:

* 429 and 5xx are retried with exponential backoff seeded from config
  (`retry.initial_backoff_s` .. `retry.max_backoff_s`).
* A 429's `Retry-After` is honoured when the provider sends one, capped at
  `retry.max_retry_after_s` — a provider asking us to wait 10 minutes should fail
  the scan, not pin a Celery worker for 10 minutes.
* After `retry.max_attempts` the call RAISES. A persistent 429 (a daily cap, say)
  must surface as a failed scan with a clear error, never a silent stall — the
  stage wrapper turns the exception into scan.status=failed + scan.error.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.gateway.credentials import resolve_api_key as _resolve_api_key
from app.gateway.models_config import RetryConfig

# Re-exported so every adapter keeps importing key resolution from one place.
# The implementation moved to gateway/credentials.py when BYOK became a
# deployment mode (self-hosted env keys vs. managed per-tenant keys); adapters
# are deliberately unaware of which mode is active.
resolve_api_key = _resolve_api_key


class ProviderHTTPError(RuntimeError):
    """Retryable upstream failure (5xx / transport)."""


class ProviderRateLimited(ProviderHTTPError):
    """Upstream 429. Carries a human-readable, actionable message."""


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw)  # delta-seconds form
    except ValueError:
        return None  # HTTP-date form — fall back to our own backoff


def post_with_retry(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    retry: RetryConfig,
    timeout_s: float,
    provider: str,
    model: str,
) -> httpx.Response:
    """POST with free-tier-aware retries. Raises ProviderRateLimited /
    ProviderHTTPError once attempts are exhausted."""
    backoff = retry.initial_backoff_s
    last_error: str = ""

    for attempt in range(1, retry.max_attempts + 1):
        try:
            with httpx.Client(timeout=timeout_s) as client:
                resp = client.post(url, json=payload, headers=headers)
        except httpx.TransportError as exc:
            last_error = f"transport error: {exc}"
            if attempt == retry.max_attempts:
                raise ProviderHTTPError(
                    f"{provider}/{model}: {last_error} after {attempt} attempts"
                ) from exc
            time.sleep(min(backoff, retry.max_backoff_s))
            backoff = min(backoff * 2, retry.max_backoff_s)
            continue

        if resp.status_code == 429:
            body = resp.text[:200]
            if attempt == retry.max_attempts:
                raise ProviderRateLimited(
                    f"{provider}/{model} rate limited (HTTP 429) after "
                    f"{attempt} attempts: {body} — you are likely at a free-tier "
                    f"per-minute or per-day cap. Raise `min_interval_s` for this "
                    f"provider in config/models.yaml, use fewer prompts/repeats, "
                    f"or wait for the quota to reset."
                )
            wait = min(backoff, retry.max_backoff_s)
            if retry.respect_retry_after:
                hinted = _retry_after_seconds(resp)
                if hinted is not None:
                    if hinted > retry.max_retry_after_s:
                        raise ProviderRateLimited(
                            f"{provider}/{model} rate limited (HTTP 429) and asked "
                            f"us to wait {hinted:.0f}s, over the "
                            f"{retry.max_retry_after_s:.0f}s cap — failing instead "
                            f"of blocking a worker. Quota likely exhausted."
                        )
                    wait = hinted
            time.sleep(wait)
            backoff = min(backoff * 2, retry.max_backoff_s)
            continue

        if resp.status_code >= 500:
            last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            if attempt == retry.max_attempts:
                raise ProviderHTTPError(
                    f"{provider}/{model}: {last_error} after {attempt} attempts"
                )
            time.sleep(min(backoff, retry.max_backoff_s))
            backoff = min(backoff * 2, retry.max_backoff_s)
            continue

        return resp

    raise ProviderHTTPError(f"{provider}/{model}: exhausted retries ({last_error})")
