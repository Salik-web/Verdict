# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Minimum-facts gate, placeholder filter, and competitor selection.

The placeholder filter is applied by the EXECUTION STAGE to every generator's
context (see `sanitize_context`), not by individual generators. It used to be
called only from the comparison-page generator, so /llms.txt happily published
"⚠️ ImagineArt's real starting price" to a customer's site — it passed validation
because the claim did match the stored fact. Filtering centrally means a new
generator cannot skip the gate by forgetting to call it: the placeholders are
simply not in the context it receives, and `placeholder_violations` catches
anything a generator hardcodes anyway.

Two further defects this closes, both of which guarantee an unusable page:

1. The competitor was picked as `competitors[0]` — arbitrary — with no regard for
   which competitor we actually hold facts about. The generator was told
   "Competitor: HiggsField" while every verified fact was about Midjourney, so the
   rules obliged it to refuse every comparison.
2. Placeholder facts ("FILL_ME...", "⚠️ your real price") counted as facts. They
   pass the verified-facts validator (the claim matches the stored fact) yet say
   nothing, producing a page of "not publicly disclosed".

The principle is the same one the claim validator already enforces: refuse rather
than publish something hollow. A blocked fix returns a reason the customer can
act on ("provide facts about Midjourney"), not a broken artifact.
"""

from __future__ import annotations

import re

from app.pipeline.execution.contracts import (
    AssetDraft,
    GeneratorContext,
    VerifiedFactRef,
)

# Markers of a value nobody has filled in yet. Matched case-insensitively on the
# display string; the seed templates use FILL_ME and the ⚠️ prefix.
_PLACEHOLDER_RE = re.compile(
    r"(fill[_\s-]?me|⚠|todo|tbd|xxx+|<[^>]+>|your[\s_-]?(real|actual)\b|placeholder)",
    re.IGNORECASE,
)

# Narrower variant for scanning generated BODY TEXT. The fact-level pattern above
# includes `<[^>]+>`, which matches every HTML tag, so it can only ever be used on
# a short fact display string — never on a document.
_PLACEHOLDER_TEXT_RE = re.compile(
    r"(fill[_\s-]?me|⚠|\btbd\b|\btodo\b|your[\s_-]?(real|actual)\b)", re.IGNORECASE
)


class GenerationBlocked(Exception):
    """Raised when a fix cannot be generated honestly. Carries a customer-facing
    reason; the runner turns it into a recorded outcome, not a crash."""

    def __init__(self, reason: str, detail: dict | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


def is_placeholder(fact: VerifiedFactRef) -> bool:
    return (
        bool(_PLACEHOLDER_RE.search(fact.display or ""))
        or not (fact.display or "").strip()
    )


def real_facts(facts: list[VerifiedFactRef]) -> list[VerifiedFactRef]:
    return [f for f in facts if not is_placeholder(f)]


def sanitize_context(context: GeneratorContext) -> GeneratorContext:
    """Remove placeholder facts before ANY generator sees the context.

    This is the shared pre-generation step. A generator physically cannot publish
    a placeholder it was never handed, which is a stronger guarantee than asking
    every generator to remember to filter. What was dropped is recorded on the
    context so a blocked result can name the facts still waiting to be filled in.
    """
    kept: list[VerifiedFactRef] = []
    dropped: list[str] = []
    for f in context.verified_facts:
        if is_placeholder(f):
            dropped.append(f"{f.fact_type}/{f.key}")
        else:
            kept.append(f)
    if not dropped:
        return context
    return context.model_copy(
        update={"verified_facts": kept, "dropped_placeholder_facts": dropped}
    )


def placeholder_violations(draft: AssetDraft) -> list[str]:
    """Belt-and-braces: catch placeholders a generator produced ITSELF.

    `sanitize_context` removes unfilled facts from the input; this checks the
    output, so a generator that hardcodes "TBD" into a claim or a plain-text asset
    is rejected rather than shipped. HTML bodies are not scanned — an LLM-written
    page can legitimately contain these words in prose, and a false rejection of a
    good page is its own failure.
    """
    violations: list[str] = []
    for claim in draft.claims:
        value = claim.value or ""
        if not value.strip() or _PLACEHOLDER_TEXT_RE.search(value):
            violations.append(
                f"placeholder value for {claim.fact_type}/{claim.key}: "
                f"'{value.strip() or '(empty)'}' is not a real fact"
            )
    if draft.content_kind == "text":
        for match in dict.fromkeys(_PLACEHOLDER_TEXT_RE.findall(draft.content)):
            token = match[0] if isinstance(match, tuple) else match
            violations.append(
                f"placeholder marker '{token}' in generated content — "
                "the asset would publish an unfilled template"
            )
    return violations


def facts_for_competitor(context: GeneratorContext, name: str) -> list[VerifiedFactRef]:
    return [
        f
        for f in context.competitor_facts
        if (f.competitor or "").strip().lower() == name.strip().lower()
    ]


def select_competitor(context: GeneratorContext) -> str | None:
    """Pick the competitor to compare against, in order of usefulness:

    1. a tracked competitor with at least one REAL fact — the only case we can
       actually publish;
    2. a tracked competitor the customer has started documenting (fact rows
       exist but are still placeholders) — so the "provide facts about X"
       message names the rival they clearly intended, not an arbitrary one;
    3. any competitor named in the facts;
    4. the first tracked competitor.

    Returns the DISPLAY name — it is printed on the generated page and quoted in
    the blocked reason shown to the customer. `display_name` only re-cases a
    leading lowercase letter, so it still matches the stored name
    case-insensitively everywhere this value is used as a lookup key.
    """
    for c in context.competitors:
        if real_facts(facts_for_competitor(context, c.name)):
            return c.display_name
    for c in context.competitors:
        if facts_for_competitor(context, c.name):
            return c.display_name
    for f in context.competitor_facts:
        if f.competitor:
            return f.competitor
    return context.competitors[0].display_name if context.competitors else None


def require_facts_for_comparison(context: GeneratorContext) -> tuple[str, list]:
    """Gate: enough verified facts to write an honest comparison?

    Returns (competitor_name, competitor_facts) or raises GenerationBlocked.
    """
    self_real = real_facts(context.self_facts)
    if not self_real:
        raise GenerationBlocked(
            f"No verified facts about {context.brand_name} yet — add at least one "
            "real pricing or feature fact before generating a comparison page.",
            {
                "missing": "self_facts",
                "self_facts_total": len(context.self_facts),
                "self_facts_real": 0,
                # Named so the customer knows which rows to fill in rather than
                # being told they have no facts at all.
                "unfilled_placeholders": context.dropped_placeholder_facts,
            },
        )

    competitor = select_competitor(context)
    if competitor is None:
        raise GenerationBlocked(
            "No competitors are configured — a comparison page needs someone to "
            "compare against.",
            {"missing": "competitors"},
        )

    comp_real = real_facts(facts_for_competitor(context, competitor))
    if not comp_real:
        known = sorted(
            {f.competitor for f in real_facts(context.competitor_facts) if f.competitor}
        )
        raise GenerationBlocked(
            f"No verified facts about {competitor} — we can't build this "
            f"comparison until you provide facts about {competitor}. "
            "Stating a rival's pricing or features unverified is a factual and "
            "legal risk, so the page is not generated.",
            {
                "missing": "competitor_facts",
                "competitor": competitor,
                "competitors_with_facts": known,
            },
        )
    return competitor, comp_real
