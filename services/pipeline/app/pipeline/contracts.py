"""Typed contracts for the Monitor stage.

These Pydantic models are the stage's interface: `ScanContext` in, `MonitorOutput`
out. Nothing in the stage reads the DB directly through these — the runner loads a
ScanContext via repositories and persists MonitorOutput via repositories, so the
stage itself is pure and testable in isolation (no DB, no network in mock mode).
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


# ── Stage input ──────────────────────────────────────────────────────────
class PromptRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: uuid.UUID
    text: str


class CompetitorRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: uuid.UUID
    name: str
    aliases: list[str] = Field(default_factory=list)
    is_self: bool = False


class ScanContext(BaseModel):
    """Everything the Monitor stage needs to run — resolved from the DB by the
    runner, so the stage never touches the database itself."""

    model_config = ConfigDict(extra="forbid")
    scan_id: uuid.UUID
    account_id: uuid.UUID
    brand_name: str
    brand_aliases: list[str] = Field(default_factory=list)
    competitors: list[CompetitorRef] = Field(default_factory=list)
    prompts: list[PromptRef]
    engines: list[str]
    repeats: int


# ── Parser output (LLM-as-judge) ─────────────────────────────────────────
class BrandRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brand: str
    position: int | None = None
    sentiment: str | None = None


class ParsedMention(BaseModel):
    """Structured extraction of one engine answer for one run."""

    model_config = ConfigDict(extra="forbid")
    brand: str
    mentioned: bool
    position: int | None = None
    sentiment: str | None = None
    sentiment_score: float | None = None
    cited_urls: list[str] = Field(default_factory=list)
    competitors: list[BrandRef] = Field(default_factory=list)


# ── Stage output ─────────────────────────────────────────────────────────
class MentionRecord(BaseModel):
    """One row destined for the mentions table — the TARGET brand's visibility
    for a single (prompt, engine, run)."""

    model_config = ConfigDict(extra="forbid")
    prompt_id: uuid.UUID
    engine: str
    run: int
    brand: str
    competitor_id: uuid.UUID | None
    mentioned: bool
    position: int | None
    sentiment: str | None
    sentiment_score: float | None
    cited_urls: list[str]


class SoVRecord(BaseModel):
    """One row destined for share_of_voice — a brand's aggregate for one engine
    (engine='all' is the cross-engine roll-up). Pre-computed, never live."""

    model_config = ConfigDict(extra="forbid")
    brand: str
    competitor_id: uuid.UUID | None
    is_self: bool
    engine: str
    mention_count: int
    mention_rate: float
    avg_position: float | None
    sov_pct: float
    details: dict = Field(default_factory=dict)


class MonitorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scan_id: uuid.UUID
    mentions: list[MentionRecord]
    share_of_voice: list[SoVRecord]
