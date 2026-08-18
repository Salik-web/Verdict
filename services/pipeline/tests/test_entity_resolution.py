# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Entity resolution: one company, one share-of-voice row.

Audit finding #4, measured on scan 4ca73df6 (37 stored rows for engine='all'):

    HiggsField (TRACKED)  0 mentions  0.000%   |  Higgsfield AI  1  2.083%
    runway     (TRACKED)  2 mentions  4.167%   |  Runway Gen-4.5 1  2.083%
    ChatGPT               1  2.083%  | ChatGPT Plus 1 | ChatGPT (GPT-5.2) 1
    Synthesia             1  2.083%  | 'Synthesia ' 1   <- trailing space
    InVideo AI            1  2.083%  | Invideo AI   1

The HiggsField split is the one that lies to a customer: we reported a tracked
competitor as measured-and-absent while the same table showed it, under another
spelling, at 2.08%.

These tests pin BOTH directions. Merging too eagerly invents a relationship
between two real companies, which is a worse failure than a split row — so every
"must NOT merge" case below is as load-bearing as the "must merge" ones.
"""

from __future__ import annotations

import uuid

import pytest

from app.pipeline.contracts import (
    BrandRef,
    CompetitorRef,
    ParsedMention,
    PromptRef,
    ScanContext,
)
from app.pipeline.monitor.entities import normalize, resolve_entities
from app.pipeline.monitor.sov import compute_sov


def _context(*competitors: str, brand: str = "Imagine Art", aliases=()) -> ScanContext:
    return ScanContext(
        scan_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        brand_name=brand,
        brand_aliases=list(aliases),
        competitors=[CompetitorRef(id=uuid.uuid4(), name=c) for c in competitors],
        prompts=[PromptRef(id=uuid.uuid4(), text="best tool")],
        engines=["primary"],
        repeats=1,
    )


def _resolve(context: ScanContext, *surfaces: str):
    return resolve_entities(context, list(surfaces))


# ── normalisation: typography only ───────────────────────────────────────
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Synthesia ", "synthesia"),
        (" Synthesia", "synthesia"),
        ("InVideo AI", "invideo ai"),
        ("Invideo AI", "invideo ai"),
        ("ChatGPT (GPT-5.2)", "chatgpt"),
        ("Magnific (formerly Freepik)", "magnific"),
        ("Runway  Gen-4.5", "runway gen-4.5"),
        ("HiggsField", "higgsfield"),
    ],
)
def test_normalize_undoes_typography(raw, expected):
    assert normalize(raw) == expected


# ── tracked brands ───────────────────────────────────────────────────────
def test_tracked_competitor_absorbs_its_own_variant():
    """THE bug: HiggsField reported at 0% while Higgsfield AI sat at 2.08%."""
    r = _resolve(_context("HiggsField"), "HiggsField", "Higgsfield AI")
    assert r("Higgsfield AI") == "HiggsField"
    assert r("HiggsField") == "HiggsField"
    assert r.merged_from["HiggsField"] == ["HiggsField", "Higgsfield AI"]


def test_product_version_folds_into_the_tracked_parent():
    r = _resolve(_context("runway"), "Runway", "runway", "Runway Gen-4.5")
    assert {r(s) for s in ("Runway", "runway", "Runway Gen-4.5")} == {"runway"}
    # The registered name wins for display, even when the engine's casing differs —
    # tracked rows must stay joinable to the competitor row.
    assert r.tracked["runway"] is True


def test_trailing_space_does_not_spawn_a_second_row():
    r = _resolve(_context(), "Synthesia", "Synthesia ")
    assert r("Synthesia ") == r("Synthesia")


def test_case_variants_of_a_discovered_brand_fold_together():
    r = _resolve(_context(), "InVideo AI", "InVideo AI", "Invideo AI")
    assert r("Invideo AI") == r("InVideo AI") == "InVideo AI"  # most frequent form


# ── product families among discovered brands ─────────────────────────────
def test_family_variants_fold_onto_an_observed_parent():
    r = _resolve(_context(), "ChatGPT", "ChatGPT Plus", "ChatGPT (GPT-5.2)")
    assert r("ChatGPT Plus") == "ChatGPT"
    assert r("ChatGPT (GPT-5.2)") == "ChatGPT"
    assert r.merged_from["ChatGPT"] == [
        "ChatGPT",
        "ChatGPT (GPT-5.2)",
        "ChatGPT Plus",
    ]


def test_a_variant_never_invents_a_parent_nobody_named():
    """Conservative rule: if the engine only ever said "ChatGPT Plus", we do not
    manufacture a "ChatGPT" entity it never mentioned."""
    r = _resolve(_context(), "ChatGPT Plus", "ChatGPT Plus")
    assert r("ChatGPT Plus") == "ChatGPT Plus"
    assert r.merged_from == {}


# ── must NOT merge ───────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "a, b",
    [
        ("Adobe", "Adobe Firefly"),  # Firefly is a product, not a qualifier
        ("Kling AI", "Kling 2.6"),  # different bases once "AI" is a qualifier
        ("Leonardo AI", "Leonardo da Vinci"),
        ("Sora", "Sora 2 by OpenAI"),  # "by OpenAI" is not a version tail
        ("Veo 3", "Veo 3.1"),  # sibling releases, no shared observed parent
        ("Magnific", "Magnific Upscaler"),
        ("Dream", "Dreamina"),  # not even a word boundary apart
    ],
)
def test_distinct_brands_stay_distinct(a, b):
    r = _resolve(_context(), a, b)
    assert r(a) != r(b), f"{a!r} and {b!r} were wrongly merged"


def test_two_tracked_competitors_are_never_merged_into_each_other():
    r = _resolve(_context("HeyGen", "Hedra"), "HeyGen", "Hedra")
    assert r("HeyGen") == "HeyGen"
    assert r("Hedra") == "Hedra"


# ── end to end through share of voice ────────────────────────────────────
def _parse(*brands: str, target: bool = False) -> ParsedMention:
    return ParsedMention(
        brand="Imagine Art",
        mentioned=target,
        competitors=[BrandRef(brand=b) for b in brands],
    )


def test_a_mentioned_tracked_competitor_is_never_reported_as_absent():
    """The customer-facing consequence: HiggsField was mentioned, so its row must
    not say 0%. Before the fix this asserted 0 and a separate untracked row held
    the mention."""
    context = _context("HiggsField", "Midjourney")
    parses = [
        ("e", _parse("Higgsfield AI", "Midjourney")),
        ("e", _parse("Midjourney")),
    ]
    rows = {r.brand: r for r in compute_sov(context, parses) if r.engine == "all"}

    assert "Higgsfield AI" not in rows
    assert rows["HiggsField"].mention_count == 1
    assert rows["HiggsField"].sov_pct > 0
    assert rows["HiggsField"].details["tracked"] is True
    assert rows["HiggsField"].details["merged_from"] == ["Higgsfield AI"]


def test_merges_do_not_double_count_within_one_answer():
    """Two spellings in the SAME answer are one mention, not two — otherwise
    merging would inflate the very number it was meant to correct."""
    context = _context()
    parses = [("e", _parse("ChatGPT", "ChatGPT Plus"))]
    rows = {r.brand: r for r in compute_sov(context, parses) if r.engine == "all"}
    assert rows["ChatGPT"].mention_count == 1


def test_share_still_sums_to_100_after_merging():
    context = _context("HiggsField", "runway")
    parses = [
        ("e", _parse("Higgsfield AI", "ChatGPT", "ChatGPT Plus")),
        ("e", _parse("Runway Gen-4.5", "ChatGPT", "Synthesia ")),
        ("e", _parse("runway", "Synthesia")),
    ]
    rows = [r for r in compute_sov(context, parses) if r.engine == "all"]
    assert round(sum(r.sov_pct for r in rows), 4) == 100.0


def test_merged_from_is_absent_when_nothing_was_merged():
    context = _context("Midjourney")
    rows = [
        r
        for r in compute_sov(context, [("e", _parse("Midjourney"))])
        if r.engine == "all"
    ]
    assert all("merged_from" not in r.details for r in rows)


def test_resolution_is_shared_across_engines():
    """A per-engine map could fold ChatGPT Plus for one engine and not another,
    leaving the 'all' roll-up disagreeing with its own parts."""
    context = _context()
    parses = [
        ("engine-a", _parse("ChatGPT")),
        ("engine-b", _parse("ChatGPT Plus")),
    ]
    brands = {r.brand for r in compute_sov(context, parses)}
    assert brands == {"ChatGPT", "Imagine Art"}
