"""Typed contracts for the Diagnosis stage.

`DiagnosisContext` in, `DiagnosisOutput` out. The stage is pure w.r.t. the DB and
the network is reached only through an injected Fetcher, so it's testable in
isolation with a fake fetcher and the gateway in mock mode.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Layer = Literal["seo", "geo", "crawler", "llms_txt"]
Severity = Literal["info", "low", "medium", "high", "urgent"]


class DiagnosisContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: uuid.UUID
    scan_id: uuid.UUID | None = None
    brand_name: str
    brand_aliases: list[str] = Field(default_factory=list)
    target_url: str  # the customer's site to audit
    competitor_urls: list[str] = Field(default_factory=list)  # cited third-party URLs


class Finding(BaseModel):
    """One observation. ok=True is a pass (kept for the report); ok=False with a
    gap_type becomes a persisted Gap."""

    model_config = ConfigDict(extra="forbid")
    layer: Layer
    code: str
    ok: bool
    severity: Severity
    summary: str
    gap_type: str | None = None
    detail: dict = Field(default_factory=dict)


class BotVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    category: Literal["training", "search"]
    allowed: bool


class BotAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    robots_found: bool
    verdicts: list[BotVerdict]
    blocked_search_bots: list[str]
    traps_triggered: list[str]


class Gap(BaseModel):
    """A taxonomy-mapped, actionable gap destined for the gaps table."""

    model_config = ConfigDict(extra="forbid")
    gap_type: str
    fix_type: str
    layer: str
    severity: Severity
    rank_score: float
    summary: str
    details: dict = Field(default_factory=dict)


class DiagnosisOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_url: str
    findings: list[Finding]
    gaps: list[Gap]
    bot_audit: BotAudit
