"""Membership guard for the LLM-as-judge parser.

The parser (a small model) sometimes echoes the "Known competitors" list back as
brands it "found", marking them mentioned even when they never appear in the
answer — fabricating share of voice. This guard is the deterministic belt to that
suspenders: a brand survives ONLY if its name (or a tracked alias) literally
occurs in the answer text. Applied to the target brand too — if the parser says
the target is mentioned but no term appears, it is dropped to mentioned=False.

It also assigns `position` deterministically from first-occurrence order in the
answer, because the model returns null/unreliable ranks (see #4): a brand's rank
is where it first appears relative to the other brands actually present. That is a
defensible, reproducible proxy for recommendation order in a listicle answer, and
never leaves the column empty.

Pure and text-only — no gateway, no DB. `answer_text` is the verbatim engine
answer (the same text stored in mentions.raw_response_ref), so this runs
identically live and on a re-parse of stored answers.
"""

from __future__ import annotations

from collections.abc import Callable

from app.pipeline.contracts import BrandRef, ParsedMention, ScanContext


def _norm_terms(name: str, aliases: list[str]) -> list[str]:
    return [t.lower() for t in [name, *aliases] if t and t.strip()]


def build_terms_for(context: ScanContext) -> Callable[[str], list[str]]:
    """Return terms_for(brand) -> the lowercased name+aliases to test in the text.

    A tracked competitor is checked by any of its aliases (so "Globex" counts for
    "Globex Insights"); an untracked/discovered brand is checked by its own name.
    """
    lookup: dict[str, list[str]] = {}
    for c in context.competitors:
        terms = _norm_terms(c.name, list(c.aliases or []))
        for key in terms:
            lookup[key] = terms

    def terms_for(brand: str) -> list[str]:
        return lookup.get(brand.lower(), [brand.lower()])

    return terms_for


def _first_index(text_lower: str, terms: list[str]) -> int | None:
    """Earliest character index at which any term occurs, or None if none do."""
    hits = [i for i in (text_lower.find(t) for t in terms) if i >= 0]
    return min(hits) if hits else None


def apply_membership_guard(
    parsed: ParsedMention,
    answer_text: str,
    *,
    self_terms: list[str],
    terms_for: Callable[[str], list[str]],
) -> ParsedMention:
    """Drop brands not present in `answer_text` and assign first-occurrence ranks.

    Returns a new ParsedMention; the input is not mutated. `cited_urls` and the
    parser's sentiment are preserved for surviving brands.
    """
    text_lower = (answer_text or "").lower()

    self_idx = _first_index(text_lower, [t.lower() for t in self_terms if t])
    self_present = self_idx is not None

    kept: list[tuple[int, BrandRef]] = []
    for c in parsed.competitors:
        idx = _first_index(text_lower, terms_for(c.brand))
        if idx is not None:
            kept.append((idx, c))

    # Deterministic ranks: order every present brand (target + survivors) by where
    # it first appears, then number them 1..n.
    entries: list[tuple[int, str, BrandRef | None]] = []
    if self_present:
        entries.append((self_idx, "self", None))
    entries.extend((idx, "comp", c) for idx, c in kept)
    entries.sort(key=lambda e: e[0])

    self_position: int | None = None
    comp_position: dict[int, int] = {}
    for rank, (_, kind, ref) in enumerate(entries, start=1):
        if kind == "self":
            self_position = rank
        elif ref is not None:
            comp_position[id(ref)] = rank

    competitors = [
        BrandRef(brand=c.brand, position=comp_position[id(c)], sentiment=c.sentiment)
        for _, c in kept
    ]

    return ParsedMention(
        brand=parsed.brand,
        mentioned=self_present,
        position=self_position if self_present else None,
        sentiment=parsed.sentiment if self_present else None,
        sentiment_score=parsed.sentiment_score if self_present else None,
        cited_urls=parsed.cited_urls,
        competitors=competitors,
    )
