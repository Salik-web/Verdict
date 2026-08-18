# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Which engines this deployment can actually call.

A user who supplies only a Perplexity key must get a working Perplexity-only
scan — not an error, and not a scan that dies on its first Gemini call. So a
missing key is a *state* ("engine unavailable, set PERPLEXITY_API_KEY"), decided
up front and reported, rather than an exception thrown mid-scan after other
engines have already been billed.

Availability is per (task, mode) because that is what config/models.yaml maps: a
provider is only relevant to a scan if some task resolves to it in the active
mode. Mock needs no key at all, which is what keeps the whole pipeline runnable
with nothing configured.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.gateway.credentials import resolve_api_key
from app.gateway.models_config import ModelsConfig, get_models_config
from app.gateway.types import GatewayMode


@dataclass(frozen=True)
class EngineStatus:
    """Whether one task can be served in one mode, and why not if it cannot."""

    task: str
    mode: GatewayMode
    provider: str
    model: str
    available: bool
    reason: str | None = None
    #: The env var whose absence disabled it — what the operator has to set.
    missing_key_env: str | None = None

    @property
    def label(self) -> str:
        return f"{self.provider}/{self.model}"


def task_status(
    task: str,
    mode: GatewayMode,
    config: ModelsConfig | None = None,
) -> EngineStatus:
    """Can `task` be served in `mode` with the credentials this process has?"""
    config = config or get_models_config()
    try:
        target = config.resolve(task, mode)
    except Exception as exc:
        return EngineStatus(
            task=task,
            mode=mode,
            provider="?",
            model="?",
            available=False,
            reason=f"not configured for mode '{mode}': {exc}",
        )

    provider_cfg = config.providers.get(target.provider)
    if provider_cfg is None:
        return EngineStatus(
            task=task,
            mode=mode,
            provider=target.provider,
            model=target.model,
            available=False,
            reason=f"provider '{target.provider}' is not defined in models.yaml",
        )

    # Mock serves canned fixtures; that is the whole point of it needing no key.
    if provider_cfg.type == "mock" or not provider_cfg.api_key_env:
        return EngineStatus(
            task=task,
            mode=mode,
            provider=target.provider,
            model=target.model,
            available=True,
        )

    if resolve_api_key(provider_cfg.api_key_env):
        return EngineStatus(
            task=task,
            mode=mode,
            provider=target.provider,
            model=target.model,
            available=True,
        )

    return EngineStatus(
        task=task,
        mode=mode,
        provider=target.provider,
        model=target.model,
        available=False,
        reason=(
            f"{provider_cfg.api_key_env} is not set — "
            f"set it to enable {target.provider}/{target.model} for '{task}'"
        ),
        missing_key_env=provider_cfg.api_key_env,
    )


def all_task_statuses(
    mode: GatewayMode, config: ModelsConfig | None = None
) -> list[EngineStatus]:
    """Status of every configured task, for a start-up report or a UI panel."""
    config = config or get_models_config()
    return [task_status(task, mode, config) for task in sorted(config.tasks)]
