"""Measurement: ask one engine one prompt, via the gateway 'measurement' task.

Kept deliberately thin — the gateway owns provider choice, retries, caching,
rate limiting, and cost logging. Adding a real engine is a gateway task in
models.yaml, not a change here.
"""

from __future__ import annotations

import uuid

from app.gateway import Gateway
from app.gateway.types import GatewayResponse, Message
from app.pipeline.contracts import PromptRef


def measure_once(
    gateway: Gateway,
    *,
    account_id: uuid.UUID,
    scan_id: uuid.UUID,
    prompt: PromptRef,
    gateway_task: str,
    scenario: str | None,
) -> GatewayResponse:
    """Query the engine once with the buyer's prompt (as a user would type it)."""
    return gateway.call(
        gateway_task,
        [Message(role="user", content=prompt.text)],
        account_id=account_id,
        scan_id=scan_id,
        scenario=scenario,
    )
