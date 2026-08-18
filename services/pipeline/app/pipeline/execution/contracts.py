# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Typed contracts for the Plan + Execute stage."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ClaimAbout = Literal["self", "competitor", "general"]


# ── Planner ──────────────────────────────────────────────────────────────
class GapInput(BaseModel):
    """A gap to plan/fix (from diagnosis / the gaps table)."""

    model_config = ConfigDict(extra="forbid")
    gap_id: uuid.UUID | None = None
    gap_type: str
    fix_type: str
    prompt_ids: list[uuid.UUID] = Field(default_factory=list)
    details: dict = Field(default_factory=dict)


class PlanItem(BaseModel):
    """One deduped, scored unit of work in the backlog."""

    model_config = ConfigDict(extra="forbid")
    fix_type: str
    gap_type: str
    score: float
    gap_ids: list[uuid.UUID]
    target_prompt_ids: list[uuid.UUID]
    factors: dict[str, float]


class Backlog(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[PlanItem]


# ── Generation ───────────────────────────────────────────────────────────
class VerifiedFactRef(BaseModel):
    """An authoritative fact the generator may state.

    `about` distinguishes facts about the customer from facts about a named
    competitor — both live in verified_facts (no schema change); the convention is
    that the row's jsonb `value` carries {"display": ..., "about": ...,
    "competitor": ...}. Competitor facts exist so a comparison page can state a
    rival's real pricing instead of the model inventing one.
    """

    model_config = ConfigDict(extra="forbid")
    fact_type: str
    key: str
    display: str
    about: ClaimAbout = "self"
    competitor: str | None = None


class CompetitorRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    domain: str | None = None
    aliases: list[str] = Field(default_factory=list)

    @property
    def display_name(self) -> str:
        """The name to print on a customer-facing page.

        Competitors are stored however the customer typed them, so an entry like
        `runway` shipped verbatim into a generated /llms.txt. Deliberately
        conservative: prefer an alias that is the SAME name with real casing
        ("Runway"), and otherwise only capitalise a leading lowercase letter.
        Never re-case the interior — "HiggsField" and "iPhone" must survive.
        """
        for candidate in [self.name, *self.aliases]:
            if candidate.lower() == self.name.lower() and any(
                c.isupper() for c in candidate
            ):
                return candidate
        return self.name[:1].upper() + self.name[1:] if self.name else self.name


class GeneratorContext(BaseModel):
    """Everything a generator needs — resolved from the DB by the runner."""

    model_config = ConfigDict(extra="forbid")
    account_id: uuid.UUID
    # Carried purely so the generation call can be COST-ATTRIBUTED to the scan
    # that caused it. Without it the row lands with scan_id NULL and per-scan cost
    # silently undercounts what a scan actually costs.
    scan_id: uuid.UUID | None = None
    brand_name: str
    brand_aliases: list[str] = Field(default_factory=list)
    target_url: str | None = None
    competitors: list[CompetitorRef] = Field(default_factory=list)
    verified_facts: list[VerifiedFactRef] = Field(default_factory=list)
    target_prompt_ids: list[uuid.UUID] = Field(default_factory=list)
    # Facts removed by the shared placeholder gate before any generator ran, as
    # "fact_type/key" strings. Kept so a blocked/empty result can say WHICH facts
    # are still unfilled instead of "you have no facts" when the customer has
    # clearly started filling them in.
    dropped_placeholder_facts: list[str] = Field(default_factory=list)

    def fact(
        self, fact_type: str, key: str, about: ClaimAbout | None = None
    ) -> VerifiedFactRef | None:
        """Look up the backing fact for a claim.

        When `about` is given, a fact with that subject wins — a self fact and a
        competitor fact can share (fact_type, key), and returning the wrong one
        turned a correct claim into a bogus "wrong subject" violation. Falls back
        to any match on (fact_type, key) so a genuine subject mismatch is still
        reported as a mismatch rather than as "not in verified_facts".
        """
        fallback: VerifiedFactRef | None = None
        for f in self.verified_facts:
            if f.fact_type != fact_type or f.key != key:
                continue
            if about is None or f.about == about:
                return f
            if fallback is None:
                fallback = f
        return fallback

    @property
    def self_facts(self) -> list[VerifiedFactRef]:
        return [f for f in self.verified_facts if f.about == "self"]

    @property
    def competitor_facts(self) -> list[VerifiedFactRef]:
        return [f for f in self.verified_facts if f.about == "competitor"]


class Claim(BaseModel):
    """A customer/competitor claim the generator made; 'self' claims must be
    backed by a verified fact."""

    model_config = ConfigDict(extra="forbid")
    fact_type: str
    key: str
    value: str
    about: ClaimAbout = "self"


class AssetDraft(BaseModel):
    """A generator's raw output, before validation/sanitization."""

    model_config = ConfigDict(extra="forbid")
    asset_type: str
    fix_type: str
    title: str
    content: str  # HTML for pages, plain text for robots/llms
    content_kind: Literal["html", "text"] = "html"
    schema_jsonld: dict | None = None
    claims: list[Claim] = Field(default_factory=list)
    target_prompt_ids: list[uuid.UUID] = Field(default_factory=list)


class Asset(BaseModel):
    """A validated, deliverable asset (or a rejected one, flagged)."""

    model_config = ConfigDict(extra="forbid")
    asset_type: str
    fix_type: str
    title: str
    content: str  # sanitized
    content_kind: Literal["html", "text"]
    schema_jsonld: dict | None
    claims: list[Claim]
    target_prompt_ids: list[uuid.UUID]
    validation_state: Literal["passed", "failed"]
    status: Literal["validated", "rejected"]
    violations: list[str] = Field(default_factory=list)


class ExecutionOutput(BaseModel):
    """The result of Plan + Execute.

    An asset is the OPTIONAL part. Planning always runs and always produces a
    backlog; generation only happens when a Generator is registered for the
    top-ranked fix_type. The open-source distribution registers none, so
    `asset is None` with a populated backlog is the ordinary outcome, not an
    error — see registry.py. `unsupported_fix_types` names the ranked items we
    could not build, in rank order, so the caller can report exactly which fix
    a generator is missing for.
    """

    model_config = ConfigDict(extra="forbid")
    backlog: Backlog
    plan_item: PlanItem | None = None
    asset: Asset | None = None
    unsupported_fix_types: list[str] = Field(default_factory=list)
    reason: str | None = None

    @property
    def produced_asset(self) -> bool:
        return self.asset is not None
