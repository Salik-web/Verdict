"""Typed boundary objects for the model gateway.

These are the contract every caller and provider speaks. `task` is a plain
string validated against the config at call time (tasks are data-driven, not a
hardcoded enum).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Role = Literal["system", "user", "assistant"]
GatewayMode = Literal["mock", "dev", "prod"]


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role
    content: str


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @model_validator(mode="after")
    def _fill_total(self) -> Usage:
        if self.total_tokens == 0:
            object.__setattr__(
                self, "total_tokens", self.prompt_tokens + self.completion_tokens
            )
        return self


class ProviderResult(BaseModel):
    """What a provider returns before the gateway prices it."""

    text: str
    usage: Usage
    raw: dict[str, Any] | None = None


class GatewayResponse(BaseModel):
    """call(...) -> {text, usage, cost, model}, plus provenance for tracing."""

    text: str
    usage: Usage
    cost_usd: Decimal = Field(default=Decimal("0"))
    model: str
    provider: str
    mode: GatewayMode
    cached: bool = False
    scenario: str | None = None
