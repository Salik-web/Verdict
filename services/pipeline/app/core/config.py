"""Settings for the pipeline service.

Validated once at import via pydantic-settings. Reads from the process
environment and an optional .env file. Model API keys default to blank — the
pipeline runs fully in mock mode without them (real keys are a one-line switch
added in a later phase). Never log this object: it holds secrets.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"

    # Shared Postgres — must match apps/api and infra/.env.
    database_url: str = "postgresql+psycopg://geo:geo@localhost:5432/geo"

    # Redis: Celery broker + result backend.
    redis_url: str = "redis://localhost:6379/0"

    # Internal service-to-service auth. Must match apps/api's value.
    internal_shared_secret: str = Field(min_length=8)

    # Gateway mode selects how model calls are served. Default `mock` runs the
    # whole pipeline with NO API keys. dev = free providers, prod = paid models.
    # Switching modes is this one env var — no code change.
    gateway_mode: Literal["mock", "dev", "prod"] = "mock"

    # Model provider keys — BLANK for now. Read only by non-mock modes; the key
    # for each provider is named in config/models.yaml (api_key_env).
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    google_api_key: str | None = None
    perplexity_api_key: str | None = None
    deepseek_api_key: str | None = None
    moonshot_api_key: str | None = None
    groq_api_key: str | None = None
    openrouter_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor (import-safe, instantiated on first use)."""
    return Settings()
