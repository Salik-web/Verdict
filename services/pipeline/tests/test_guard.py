"""Membership guard: fabricated brands are dropped; ranks come from the text.

Pure, no gateway/DB. Mirrors the real failure: the parser echoed the tracked
competitors (HiggsField/Midjourney) though neither was in the answer, and it
returned null positions.
"""

from __future__ import annotations

import uuid

from app.pipeline.contracts import BrandRef, CompetitorRef, ParsedMention, ScanContext
from app.pipeline.monitor.guard import apply_membership_guard, build_terms_for

SELF = uuid.UUID("00000000-0000-0000-0000-0000000000a0")
GLOBEX = uuid.UUID("00000000-0000-0000-0000-0000000000a1")


def _context() -> ScanContext:
    return ScanContext(
        scan_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        brand_name="Imagine Art",
        brand_aliases=["ImagineArt"],
        competitors=[
            CompetitorRef(id=SELF, name="Imagine Art", aliases=["ImagineArt"],
                          is_self=True),
            CompetitorRef(id=GLOBEX, name="Globex Insights", aliases=["Globex"]),
        ],
        prompts=[],
        engines=["primary"],
        repeats=1,
    )


def _guard(parsed: ParsedMention, text: str) -> ParsedMention:
    ctx = _context()
    return apply_membership_guard(
        parsed,
        text,
        self_terms=[ctx.brand_name, *ctx.brand_aliases],
        terms_for=build_terms_for(ctx),
    )


def test_fabricated_competitors_are_dropped():
    # The parser echoed HiggsField + Midjourney; the text mentions neither.
    parsed = ParsedMention(
        brand="Imagine Art",
        mentioned=False,
        competitors=[
            BrandRef(brand="HiggsField", position=1),
            BrandRef(brand="Midjourney", position=2),
        ],
    )
    text = "The best tools are HeyGen and Runway for video ads."
    out = _guard(parsed, text)
    assert out.competitors == []  # neither is in the text
    assert out.mentioned is False


def test_real_brands_survive_and_get_first_occurrence_positions():
    parsed = ParsedMention(
        brand="Imagine Art",
        mentioned=False,
        competitors=[
            # deliberately out of order + null positions, like the weak model
            BrandRef(brand="Runway", position=None),
            BrandRef(brand="HeyGen", position=None),
        ],
    )
    text = "Top picks: HeyGen first, then Runway later in the list."
    out = _guard(parsed, text)
    by = {c.brand: c.position for c in out.competitors}
    assert by == {"HeyGen": 1, "Runway": 2}  # order of appearance, not input order


def test_self_is_guarded_too():
    # Parser CLAIMS the target is mentioned, but it isn't in the text -> dropped.
    parsed = ParsedMention(brand="Imagine Art", mentioned=True, position=1)
    out = _guard(parsed, "Only HeyGen and Runway are recommended here.")
    assert out.mentioned is False
    assert out.position is None


def test_self_alias_counts_and_ranks_with_competitors():
    parsed = ParsedMention(
        brand="Imagine Art",
        mentioned=True,
        competitors=[BrandRef(brand="Globex Insights")],
    )
    # "ImagineArt" (an alias) appears AFTER Globex -> position 2.
    text = "Globex Insights leads, but ImagineArt is a solid alternative."
    out = _guard(parsed, text)
    assert out.mentioned is True
    assert out.position == 2
    assert out.competitors[0].brand == "Globex Insights"
    assert out.competitors[0].position == 1


def test_tracked_competitor_matched_by_alias():
    # "Globex" alone should satisfy the tracked "Globex Insights".
    parsed = ParsedMention(
        brand="Imagine Art",
        mentioned=False,
        competitors=[BrandRef(brand="Globex Insights")],
    )
    out = _guard(parsed, "Most teams pick Globex for this.")
    assert [c.brand for c in out.competitors] == ["Globex Insights"]
    assert out.competitors[0].position == 1
