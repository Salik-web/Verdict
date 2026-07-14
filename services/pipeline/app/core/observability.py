"""Structured logging + optional Sentry for the pipeline.

Logging is stdlib-only (no new runtime dep): one configured root logger at the
settings level. We deliberately log only ids, counts, and stage/status — never
the Settings object, request bodies, scraped page content, model output, or
credentials. Sentry is initialised **only when SENTRY_DSN is set**, so mock/dev/
test runs are unaffected and the service boots with no secret required; when it is
set, a scrubber drops known-sensitive fields before any event leaves the process.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import get_settings

_LOG_CONFIGURED = False
_SENTRY_STARTED = False

# Header / field names that must never leave the process in an error report.
_SCRUB_KEYS = {
    "x-internal-secret",
    "authorization",
    "cookie",
    "set-cookie",
    "internal_shared_secret",
    "database_url",
    "redis_url",
    "openai_api_key",
    "anthropic_api_key",
    "google_api_key",
    "perplexity_api_key",
    "deepseek_api_key",
    "moonshot_api_key",
    "groq_api_key",
    "openrouter_api_key",
    "sentry_dsn",
    "password",
    "token",
    "secret",
    "ciphertext",
    "encrypted_dek",
}


def configure_logging() -> None:
    """Idempotently configure the root logger at the settings log level."""
    global _LOG_CONFIGURED
    if _LOG_CONFIGURED:
        return
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
    _LOG_CONFIGURED = True


def _scrub(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any]:
    """Sentry before_send: recursively redact known-sensitive keys."""

    def redact(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {
                k: ("[redacted]" if k.lower() in _SCRUB_KEYS else redact(v))
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [redact(v) for v in obj]
        return obj

    return redact(event)


def init_sentry() -> bool:
    """Wire Sentry iff SENTRY_DSN is set. Returns True when actually started.

    PII is never sent (`send_default_pii=False`) and a scrubber redacts secrets.
    Safe to call from both the FastAPI app and the Celery worker on boot."""
    global _SENTRY_STARTED
    if _SENTRY_STARTED:
        return True
    dsn = get_settings().sentry_dsn
    if not dsn:
        return False

    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.fastapi import FastApiIntegration

    sentry_sdk.init(
        dsn=dsn,
        environment=get_settings().environment,
        integrations=[FastApiIntegration(), CeleryIntegration()],
        send_default_pii=False,
        traces_sample_rate=0.0,
        before_send=_scrub,
    )
    _SENTRY_STARTED = True
    return True
