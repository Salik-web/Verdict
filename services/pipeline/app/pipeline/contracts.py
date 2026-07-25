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


# ── Citations ────────────────────────────────────────────────────────────
class CitationSource(BaseModel):
    """A source an engine cited. `url` is what the engine returns verbatim (for
    grounded Gemini that's a vertexaisearch redirect); `title` is the publisher
    domain the engine attributes it to (e.g. "uefa.com") — the useful GEO signal
    for 'which sources does the engine trust'. Stored as-is in mentions.cited_urls.
    """

    model_config = ConfigDict(extra="forbid")
    url: str
    title: str | None = None


# ── Parser output (LLM-as-judge) ─────────────────────────────────────────
# extra="ignore" (not forbid): this is untrusted LLM output. A real judge model
# routinely adds fields we didn't ask for (e.g. a per-competitor `mentioned` or
# `sentiment_score`); we read only the fields below, so surplus keys should be
# dropped, not crash the parse. The membership guard re-derives what matters.
class BrandRef(BaseModel):
    model_config = ConfigDict(extra="ignore")
    brand: str
    position: int | None = None
    sentiment: str | None = None


class ParsedMention(BaseModel):
    """Structured extraction of one engine answer for one run."""

    model_config = ConfigDict(extra="ignore")
    brand: str
    mentioned: bool
    position: int | None = None
    sentiment: str | None = None
    sentiment_score: float | None = None
    cited_urls: list[str] = Field(default_factory=list)
    competitors: list[BrandRef] = Field(default_factory=list)


# ── Stage output ─────────────────────────────────────────────────────────
class MentionRecord(BaseModel):
    """One row for the mentions table: how ONE brand fared in a single
    (prompt, engine, run) answer. There is one row for the target brand plus one
    for each competitor the engine named, so per-run/per-competitor data is
    persisted, not just the aggregate.

    `raw_response` (the engine's verbatim answer) and `cited_urls` are per-answer
    facts, so they're carried only on the target row; competitor rows leave them
    empty rather than duplicating the same prose N times.
    """

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
    cited_urls: list[CitationSource] = Field(default_factory=list)
    # Verbatim engine answer (target row only). Grounded calls cost money — this
    # is the evidence to audit the parser's extraction against.
    raw_response: str | None = None


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
