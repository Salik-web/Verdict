# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""The open-source shape: **zero generators registered**.

Planning must still run, rank gaps and emit a backlog; execution must report
"no generator available for this fix_type" as an ordinary outcome and never
raise. Advisory fix types (remove_noindex, add_freshness_signals) always worked
this way — these tests pin that as the general case.

Also covers the extension point itself, since that is what a downstream product
builds on: registering a generator must change the outcome with no edit to this
repo.
"""

from __future__ import annotations

import uuid

import pytest

from app.pipeline.execution.base import Generator
from app.pipeline.execution.contracts import (
    AssetDraft,
    GapInput,
    GeneratorContext,
    PlanItem,
)
from app.pipeline.execution.registry import (
    build_registry,
    clear_generators,
    register_generator,
)
from app.pipeline.execution.stage import generate_top_fix

GAPS = [
    GapInput(
        gap_id=uuid.uuid4(),
        gap_type="missing_llms_txt",
        fix_type="add_llms_txt",
        details={"fix_type": "add_llms_txt"},
    ),
    GapInput(
        gap_id=uuid.uuid4(),
        gap_type="weak_page_structure",
        fix_type="restructure_for_answers",
        details={"fix_type": "restructure_for_answers"},
    ),
]


@pytest.fixture(autouse=True)
def _no_leaked_registrations():
    clear_generators()
    yield
    clear_generators()


def _context() -> GeneratorContext:
    return GeneratorContext(account_id=uuid.uuid4(), brand_name="Acme Analytics")


# ── the stock distribution ───────────────────────────────────────────────
def test_stock_registry_is_empty():
    assert build_registry() == {}


def test_execution_with_no_generators_still_plans_and_does_not_raise():
    out = generate_top_fix(GAPS, _context(), registry={})

    # The backlog is the deliverable, and it is still ranked.
    assert [i.fix_type for i in out.backlog.items] == [
        "add_llms_txt",
        "restructure_for_answers",
    ]
    assert out.backlog.items[0].score > out.backlog.items[1].score

    # No asset, and that is a reported outcome rather than an error.
    assert out.produced_asset is False
    assert out.asset is None
    assert out.plan_item is None
    assert out.unsupported_fix_types == [
        "add_llms_txt",
        "restructure_for_answers",
    ]
    assert "No generator available for this fix_type" in out.reason


def test_advisory_only_backlog_is_the_same_ordinary_outcome():
    """`remove_noindex` never had a generator. It must look exactly like every
    other unsupported fix type now — no special case."""
    advisory = [
        GapInput(
            gap_type="page_noindex",
            fix_type="remove_noindex",
            details={"fix_type": "remove_noindex"},
        )
    ]
    out = generate_top_fix(advisory, _context(), registry={})
    assert out.produced_asset is False
    assert out.unsupported_fix_types == ["remove_noindex"]


def test_no_rankable_gaps_is_not_an_error():
    out = generate_top_fix([], _context(), registry={})
    assert out.backlog.items == []
    assert out.produced_asset is False
    assert "nothing to plan" in out.reason.lower()


# ── the extension point ──────────────────────────────────────────────────
class _Stub(Generator):
    fix_type = "add_llms_txt"
    asset_type = "llms_txt"

    def generate(self, item: PlanItem, context: GeneratorContext) -> AssetDraft:
        return AssetDraft(
            asset_type=self.asset_type,
            fix_type=self.fix_type,
            title="t",
            content="# Acme Analytics",
            content_kind="text",
        )


def test_registering_a_generator_changes_the_outcome():
    register_generator(_Stub())
    assert set(build_registry()) == {"add_llms_txt"}

    out = generate_top_fix(GAPS, _context())
    assert out.produced_asset is True
    assert out.plan_item.fix_type == "add_llms_txt"
    assert out.asset.asset_type == "llms_txt"
    # Nothing outranked it, so nothing was skipped.
    assert out.unsupported_fix_types == []


def test_a_partial_registry_skips_past_what_it_cannot_build():
    """Registering only the LOWER-ranked fix must not silently drop the higher
    one — it is reported as unsupported and execution moves down the list."""

    class _Restructure(_Stub):
        fix_type = "restructure_for_answers"
        asset_type = "page_outline"

    out = generate_top_fix(
        GAPS, _context(), registry={"restructure_for_answers": _Restructure()}
    )
    assert out.produced_asset is True
    assert out.plan_item.fix_type == "restructure_for_answers"
    assert out.unsupported_fix_types == ["add_llms_txt"]
