# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Parser recall: does the judge extract the brands the answer actually names?

Audit finding #2. The membership guard made extraction PRECISE (100% of stored
brands are traceable to the answer text) but nothing measured whether it was
COMPLETE. It wasn't: groq/llama-3.1-8b-instant found 41 of the 129 brands named
across the ten stored answers of scan 4ca73df6 — 31.8% — and returned nothing at
all from one 2,968-character answer. Share of voice was being computed on under a
third of the market, which is a wrong number, not a noisy one.

`tests/fixtures/parser_recall.json` is those ten verbatim answers with a curated
list of the brands each one names. Ground truth is deliberately conservative:
model names belonging to a listed product ("Phoenix" inside Leonardo AI),
techniques (LoRA, ControlNet) and non-tool companies (CNET) are excluded, and the
fixture builder asserts every ground-truth brand occurs literally in its answer.

Two of the ten answers are empty — that is audit finding #3, and they are
excluded from the ratio here rather than counted as answers naming nobody.

The live benchmark runs the configured dev model and is opt-in (it costs real
calls); the offline tests guard the harness itself, so a regression in the
harness can't hide a regression in the parser.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import uuid

import pytest

from app.pipeline.contracts import CompetitorRef, PromptRef, ScanContext

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "parser_recall.json"

# Measured 2026-07-28 on this fixture, for the record:
#   groq/llama-3.1-8b-instant     41/129 = 31.8%   (what was shipping)
#   gemini/gemini-3.1-flash-lite 125/129 = 96.9%   first run
#                                122/129 = 94.6%   second run (sampling variance)
# The residual misses are consistently the Veo/Sora video-model family, where the
# judge returns the vendor's phrasing ("Google Veo") rather than the version.
#
# The floor sits below the measured band so ordinary model drift doesn't fail the
# build, but any regression toward the llama-8b era does.
MEASURED = {"groq/llama-3.1-8b-instant": 0.318, "gemini/gemini-3.1-flash-lite": 0.946}
RECALL_FLOOR = 0.85


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _norm(s: str) -> str:
    s = s.lower().replace("·", "-").replace("‑", "-").replace("–", "-")
    s = re.sub(r"[^a-z0-9.\- ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip(" .-")


def matched(truth: str, extracted: list[str]) -> bool:
    """A ground-truth brand counts as found if an extraction names it.

    Containment either way, so "Google Veo 3" satisfies "Veo 3" and "ChatGPT
    (GPT-5.2)" satisfies "ChatGPT" — the parser is being judged on whether it saw
    the brand, not on how it spelled it.
    """
    t = _norm(truth)
    return any(_norm(e) == t or t in _norm(e) or _norm(e) in t for e in extracted)


def measure_recall(extract) -> tuple[int, int, list[tuple[str, list[str]]]]:
    """extract(answer_text) -> [brand names].

    Returns (found, total, per-answer misses).
    """
    data = load_fixture()
    found = total = 0
    misses: list[tuple[str, list[str]]] = []
    for answer in data["answers"]:
        if not answer["text"].strip():
            continue  # empty answer: a failed observation, not zero brands
        got = extract(answer["text"])
        missed = [b for b in answer["brands"] if not matched(b, got)]
        found += len(answer["brands"]) - len(missed)
        total += len(answer["brands"])
        if missed:
            misses.append((answer["label"], missed))
    return found, total, misses


def scan_context(data: dict) -> ScanContext:
    return ScanContext(
        scan_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        brand_name=data["brand_name"],
        brand_aliases=data["brand_aliases"],
        competitors=[
            CompetitorRef(
                id=uuid.uuid4(),
                name=c["name"],
                aliases=c["aliases"],
                is_self=c["is_self"],
            )
            for c in data["competitors"]
        ],
        prompts=[PromptRef(id=uuid.uuid4(), text=t) for t in data["prompts"].values()],
        engines=["primary"],
        repeats=5,
    )


# ── the fixture itself ───────────────────────────────────────────────────
def test_ground_truth_is_present_in_every_answer():
    """The benchmark is only meaningful if every brand it demands is really there."""
    data = load_fixture()
    for answer in data["answers"]:
        low = answer["text"].lower()
        for brand in answer["brands"]:
            assert brand.lower() in low, f"{answer['label']}: {brand!r} not in answer"


def test_fixture_shape_is_stable():
    data = load_fixture()
    non_empty = [a for a in data["answers"] if a["text"].strip()]
    assert len(data["answers"]) == 10
    assert len(non_empty) == 8  # two empty answers = audit finding #3
    assert sum(len(a["brands"]) for a in data["answers"]) == 129


# ── the harness ──────────────────────────────────────────────────────────
def test_a_perfect_parser_scores_100():
    data = load_fixture()
    truth = {a["text"]: a["brands"] for a in data["answers"]}
    found, total, misses = measure_recall(lambda text: truth[text])
    assert (found, total, misses) == (129, 129, [])


def test_the_harness_would_have_caught_the_shipped_parser():
    """Guards the guard: a parser that names one brand per answer must score far
    under the floor. If this ever passes, the benchmark has stopped measuring."""
    data = load_fixture()
    truth = {a["text"]: a["brands"] for a in data["answers"]}
    found, total, _ = measure_recall(lambda text: truth[text][:1])
    assert found / total < 0.15
    assert found / total < RECALL_FLOOR


def test_membership_guard_does_not_drop_correct_extractions():
    """Recall must be lost in the MODEL, never in our own post-processing: the
    guard keeps every brand that genuinely occurs in the answer."""
    from app.pipeline.contracts import BrandRef, ParsedMention
    from app.pipeline.monitor.guard import apply_membership_guard, build_terms_for

    data = load_fixture()
    context = scan_context(data)

    def extract(text: str) -> list[str]:
        answer = next(a for a in data["answers"] if a["text"] == text)
        perfect = ParsedMention(
            brand=data["brand_name"],
            mentioned=False,
            competitors=[BrandRef(brand=b) for b in answer["brands"]],
        )
        guarded = apply_membership_guard(
            perfect,
            text,
            self_terms=[data["brand_name"], *data["brand_aliases"]],
            terms_for=build_terms_for(context),
        )
        return [c.brand for c in guarded.competitors]

    found, total, misses = measure_recall(extract)
    assert (found, total) == (129, 129), f"guard dropped: {misses}"


# ── live benchmark ───────────────────────────────────────────────────────
@pytest.mark.skipif(
    os.getenv("GEO_LIVE_TESTS") != "1",
    reason="live benchmark: set GEO_LIVE_TESTS=1 (spends real processing calls)",
)
def test_configured_dev_parser_meets_the_recall_floor(capsys):
    from app.gateway.cost import NullCostSink
    from app.gateway.gateway import build_gateway
    from app.gateway.models_config import load_models_config
    from app.pipeline.monitor.parse import parse_answer

    data = load_fixture()
    context = scan_context(data)
    config = load_models_config()
    # Never cache-serve one answer's extraction for another's.
    config.cache.exclude_tasks = [*config.cache.exclude_tasks, "processing"]
    gateway = build_gateway(mode="dev", config=config, cost_sink=NullCostSink())
    target = config.resolve("processing", "dev")

    def extract(text: str) -> list[str]:
        parsed = parse_answer(gateway, context, answer_text=text, scenario=None)
        names = [c.brand for c in parsed.competitors]
        return [*names, parsed.brand] if parsed.mentioned else names

    found, total, misses = measure_recall(extract)
    with capsys.disabled():
        print(
            f"\n  {target.provider}/{target.model}: {found}/{total} = "
            f"{found / total:.1%} recall"
        )
        for label, missed in misses:
            print(f"    {label}: missed {', '.join(missed)}")
    assert found / total >= RECALL_FLOOR
