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
    model_config = ConfigDict(extra="forbid")
    fact_type: str
    key: str
    display: str


class CompetitorRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    domain: str | None = None
    aliases: list[str] = Field(default_factory=list)


class GeneratorContext(BaseModel):
    """Everything a generator needs — resolved from the DB by the runner."""

    model_config = ConfigDict(extra="forbid")
    account_id: uuid.UUID
    brand_name: str
    brand_aliases: list[str] = Field(default_factory=list)
    target_url: str | None = None
    competitors: list[CompetitorRef] = Field(default_factory=list)
    verified_facts: list[VerifiedFactRef] = Field(default_factory=list)
    target_prompt_ids: list[uuid.UUID] = Field(default_factory=list)

    def fact(self, fact_type: str, key: str) -> VerifiedFactRef | None:
        for f in self.verified_facts:
            if f.fact_type == fact_type and f.key == key:
                return f
        return None


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
    model_config = ConfigDict(extra="forbid")
    backlog: Backlog
    plan_item: PlanItem
    asset: Asset
