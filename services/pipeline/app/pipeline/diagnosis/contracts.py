# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Typed contracts for the Diagnosis stage.

`DiagnosisContext` in, `DiagnosisOutput` out. The stage is pure w.r.t. the DB and
the network is reached only through an injected Fetcher, so it's testable in
isolation with a fake fetcher and the gateway in mock mode.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Layer = Literal["seo", "geo", "crawler", "llms_txt"]
Severity = Literal["info", "low", "medium", "high", "urgent"]

# A check's epistemic state. The distinction that matters: "we looked and it is
# not there" vs "we could not find out". Only CONFIRMED_ABSENT may become a Gap —
# a CHECK_FAILED that silently became "absent" is how a 403 or a rate-limit turns
# into a confident, wrong finding on a customer's report.
CheckStatus = Literal["confirmed_present", "confirmed_absent", "check_failed"]


class Evidence(BaseModel):
    """What was actually fetched to reach a verdict. Persisted with the gap so a
    finding can be re-checked by hand later without re-running the pipeline."""

    model_config = ConfigDict(extra="forbid")
    url: str
    status: int | None = None  # None = transport failure (never got a response)
    final_url: str | None = None
    bytes: int = 0
    fetched_at: str  # ISO-8601 UTC
    note: str | None = None
    # True when only the first `bytes` of the response were analysed. An absence
    # concluded from truncated content is not an absence — it is a check that did
    # not finish, so `downgrade_truncated_absences` turns it into check_failed.
    truncated: bool = False
    # Full response size, so "we read 2 MB of 2.9 MB" is legible without refetching.
    content_bytes: int = 0


class CitedSource(BaseModel):
    """One source an engine grounded on, as the monitor recorded it.

    `title` is the publisher title when the engine supplies one (Perplexity's
    `search_results` does; Gemini's grounding metadata does not always). It is
    carried so a report can show WHAT was cited, not just the domain.
    """

    model_config = ConfigDict(extra="forbid")
    url: str
    title: str | None = None


class DiagnosisContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: uuid.UUID
    scan_id: uuid.UUID | None = None
    brand_name: str
    brand_aliases: list[str] = Field(default_factory=list)
    target_url: str  # the customer's site to audit
    competitor_urls: list[str] = Field(default_factory=list)  # cited third-party URLs
    # Everything the engines cited this scan, url + publisher title. Drives the
    # citation-list checks, which need no HTTP and therefore cannot false-positive
    # on a URL they failed to fetch (see diagnosis/citations.py).
    cited_sources: list[CitedSource] = Field(default_factory=list)


class Finding(BaseModel):
    """One observation. ok=True is a pass (kept for the report); ok=False with a
    gap_type becomes a persisted Gap — but ONLY when status is confirmed_absent.

    `confidence` is how much the check trusts its own verdict:
      1.0  definitive (a 404 on the exact URL; a sitemap-wide scan)
      ~0.4 inference from a single page (e.g. "the homepage links to no
           comparison page" does NOT mean the site has none)
      0.0  the check failed
    Low-confidence gaps are stored but never ranked, so a single-page inference
    can't surface as the top fix.
    """

    model_config = ConfigDict(extra="forbid")
    layer: Layer
    code: str
    ok: bool
    severity: Severity
    summary: str
    gap_type: str | None = None
    detail: dict = Field(default_factory=dict)
    # Left unset, status follows `ok` (a pass = confirmed_present). Checks that
    # can't reach a conclusion must set it explicitly to "check_failed".
    status: CheckStatus | None = None
    confidence: float = 1.0
    evidence: list[Evidence] = Field(default_factory=list)
    # Does this negative verdict rest on NOT FINDING something? Almost every one
    # does ("no schema", "no H1", "no comparison page"), and those cannot be
    # trusted when the page was truncated. A check that found a defect it can
    # point at — a noindex tag in the HTML we did read — sets this False, because
    # positive evidence stays valid however much of the page went unread.
    from_absence: bool = True

    @model_validator(mode="after")
    def _default_status_from_ok(self) -> Finding:
        if self.status is None:
            self.status = "confirmed_present" if self.ok else "confirmed_absent"
        return self


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
