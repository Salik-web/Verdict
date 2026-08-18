# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Three-state checks, evidence, and the confidence floor.

Regression cover for a real false positive: imagine.art has 51 comparison URLs
and a server-rendered /compare hub, but its homepage is an app shell that links
to none of them — so a homepage-only check reported "no owned comparison page"
with rank 0.81 and shipped a page the customer didn't need.
"""

from __future__ import annotations

import uuid

from app.pipeline.diagnosis.contracts import DiagnosisContext, Evidence, Finding
from app.pipeline.diagnosis.fetcher import FakeFetcher, FetchResult
from app.pipeline.diagnosis.geo import check_owned_comparison_page
from app.pipeline.diagnosis.llms_txt import check_llms_txt
from app.pipeline.diagnosis.probe import probe
from app.pipeline.diagnosis.sitemap import SitemapInventory, fetch_sitemap
from app.pipeline.diagnosis.taxonomy import finding_to_gap, findings_to_gaps
from app.pipeline.execution.contracts import GapInput
from app.pipeline.execution.planner import plan

TARGET = "https://8.8.8.8/"
APP_SHELL_HOME = FetchResult(
    url=TARGET,
    final_url=TARGET,
    status=200,
    ok=True,
    # An app-shell homepage: real links, none of them comparison pages.
    text=(
        "<html><body><a href='/image'>Image</a>"
        "<a href='/video'>Video</a></body></html>"
    ),
)


def _sitemap(urls: list[str]) -> SitemapInventory:
    return SitemapInventory(urls=urls, evidence=[], ok=True)


def _page(url: str, text: str, status: int = 200) -> FetchResult:
    return FetchResult(
        url=url, final_url=url, status=status, ok=status < 400, text=text
    )


# ── the false positive ───────────────────────────────────────────────────
def test_sitemap_comparison_urls_prevent_the_false_positive():
    """The imagine.art case: homepage links to no comparison page, but the site
    has plenty. Must NOT be a gap."""
    sm = _sitemap(
        [
            "https://x/compare/imagineart-vs-runway",
            "https://x/blogs/midjourney-vs-stable-diffusion-vs-imagine-art",
            "https://x/pricing",
        ]
    )
    f = check_owned_comparison_page(APP_SHELL_HOME, sm)
    assert f.ok is True
    assert f.status == "confirmed_present"
    assert finding_to_gap(f) is None


def test_sitemap_without_comparison_urls_is_a_confident_gap():
    sm = _sitemap(["https://x/", "https://x/pricing", "https://x/docs"])
    f = check_owned_comparison_page(APP_SHELL_HOME, sm)
    assert f.ok is False and f.status == "confirmed_absent"
    assert f.confidence == 1.0
    gap = finding_to_gap(f)
    assert gap is not None and gap.rank_score > 0


def test_unreadable_sitemap_makes_homepage_absence_low_confidence():
    """Without an inventory we can only see the homepage — that is a guess about
    the site, and must be marked as one."""
    sm = SitemapInventory(urls=[], evidence=[], ok=False)
    f = check_owned_comparison_page(APP_SHELL_HOME, sm)
    assert f.ok is False
    assert f.confidence < 0.5
    assert f.detail["basis"] == "homepage_anchors_only"


def test_low_confidence_gap_is_stored_but_never_ranked():
    """The floor applies to RANKING: a weak inference cannot become the top fix."""
    weak = GapInput(
        gap_id=uuid.uuid4(),
        gap_type="no_owned_comparison_page",
        fix_type="generate_comparison_page",
        prompt_ids=[],
        details={"detection_confidence": 0.4},
    )
    strong = GapInput(
        gap_id=uuid.uuid4(),
        gap_type="missing_llms_txt",
        fix_type="add_llms_txt",
        prompt_ids=[],
        details={"detection_confidence": 1.0},
    )
    backlog = plan([weak, strong])
    fix_types = [i.fix_type for i in backlog.items]
    assert "generate_comparison_page" not in fix_types
    assert fix_types == ["add_llms_txt"]


# ── check_failed never becomes a gap ─────────────────────────────────────
def test_blocked_llms_txt_is_check_failed_not_missing():
    """A 403 means we were refused, not that the file is absent."""
    f = check_llms_txt(
        FakeFetcher({f"{TARGET}llms.txt": _page(f"{TARGET}llms.txt", "", 403)}),
        TARGET,
    )
    assert f.status == "check_failed"
    assert f.confidence == 0.0
    assert finding_to_gap(f) is None  # the whole point


def test_real_404_llms_txt_is_a_confirmed_gap():
    f = check_llms_txt(FakeFetcher({}), TARGET)  # FakeFetcher 404s unknown URLs
    assert f.status == "confirmed_absent"
    assert f.gap_type == "missing_llms_txt"
    assert finding_to_gap(f) is not None


def test_check_failed_finding_never_produces_a_gap():
    f = Finding(
        layer="geo",
        code="x",
        ok=False,
        severity="high",
        summary="s",
        gap_type="no_owned_comparison_page",
        status="check_failed",
        confidence=0.0,
    )
    assert finding_to_gap(f) is None


# ── evidence trail ───────────────────────────────────────────────────────
def test_gap_carries_evidence_of_what_was_fetched():
    f = check_llms_txt(FakeFetcher({}), TARGET)
    gap = finding_to_gap(f)
    assert gap is not None
    ev = gap.details["evidence"]
    assert ev and ev[0]["url"].endswith("/llms.txt")
    assert ev[0]["status"] == 404
    assert ev[0]["fetched_at"]
    assert gap.details["detection_confidence"] == 1.0


# ── one gap per gap_type, reasons preserved ──────────────────────────────
def _weak(code: str, severity: str, summary: str, confidence: float = 1.0):
    """Two different checks that both mean 'weak_page_structure'."""
    return Finding(
        layer="seo" if code == "weak_headings" else "geo",
        code=code,
        ok=False,
        severity=severity,
        summary=summary,
        gap_type="weak_page_structure",
        confidence=confidence,
        detail={"h1_count": 0} if code == "weak_headings" else {"reasons": ["vague"]},
        evidence=[
            Evidence(url=TARGET, status=200, fetched_at="2026-01-01T00:00:00+00:00")
        ],
    )


def test_same_gap_type_collapses_to_one_row_keeping_both_reasons():
    findings = [
        _weak("weak_headings", "low", "Expected one H1, found 0."),
        _weak("not_quotable", "medium", "Content isn't in a quotable structure."),
    ]
    gaps = findings_to_gaps(findings)

    assert len(gaps) == 1, "one problem should be one gap, not two"
    gap = gaps[0]
    assert gap.gap_type == "weak_page_structure"

    reasons = gap.details["reasons"]
    assert len(reasons) == 2
    codes = {r["finding_code"] for r in reasons}
    assert codes == {"weak_headings", "not_quotable"}
    # Each reason keeps its own text, severity and detail — nothing is lost.
    by_code = {r["finding_code"]: r for r in reasons}
    assert "found 0" in by_code["weak_headings"]["summary"]
    assert by_code["weak_headings"]["detail"]["h1_count"] == 0
    assert by_code["not_quotable"]["severity"] == "medium"


def test_merged_gap_leads_with_its_strongest_finding():
    """The higher-severity finding sets the headline and the score."""
    gaps = findings_to_gaps(
        [
            _weak("weak_headings", "low", "Expected one H1, found 0."),
            _weak("not_quotable", "medium", "Content isn't quotable."),
        ]
    )
    gap = gaps[0]
    assert gap.severity == "medium"
    assert gap.details["finding_code"] == "not_quotable"
    assert gap.details["merged_from"] == ["not_quotable", "weak_headings"]
    # Evidence is unioned and de-duplicated (both checks read the same page).
    assert len(gap.details["evidence"]) == 1


def test_merged_gap_takes_the_highest_detection_confidence():
    gaps = findings_to_gaps(
        [
            _weak("weak_headings", "low", "H1 missing.", confidence=1.0),
            _weak("not_quotable", "low", "Not quotable.", confidence=0.3),
        ]
    )
    assert gaps[0].details["detection_confidence"] == 1.0


def test_distinct_gap_types_are_not_merged():
    gaps = findings_to_gaps(
        [
            _weak("weak_headings", "low", "H1 missing."),
            Finding(
                layer="llms_txt",
                code="llms_txt_missing",
                ok=False,
                severity="medium",
                summary="No /llms.txt.",
                gap_type="missing_llms_txt",
            ),
        ]
    )
    assert {g.gap_type for g in gaps} == {"weak_page_structure", "missing_llms_txt"}


def test_single_finding_still_gets_a_reasons_list():
    """Uniform shape for the UI: one reason is still a list of one."""
    gaps = findings_to_gaps([_weak("weak_headings", "low", "H1 missing.")])
    assert len(gaps[0].details["reasons"]) == 1


def test_probe_distinguishes_absent_from_failed():
    f = FakeFetcher(
        {
            "https://8.8.8.8/gone": _page("https://8.8.8.8/gone", "", 404),
            "https://8.8.8.8/blocked": _page("https://8.8.8.8/blocked", "", 429),
        }
    )
    assert probe(f, "https://8.8.8.8/gone").absent is True
    assert probe(f, "https://8.8.8.8/gone").failed is False
    assert probe(f, "https://8.8.8.8/blocked").failed is True
    assert probe(f, "https://8.8.8.8/blocked").absent is False


def test_sitemap_is_read_from_robots_directive():
    body = (
        '<?xml version="1.0"?><urlset><url><loc>https://8.8.8.8/a-vs-b</loc>'
        "</url></urlset>"
    )
    f = FakeFetcher(
        {
            "https://8.8.8.8/custom-sitemap.xml": _page(
                "https://8.8.8.8/custom-sitemap.xml", body
            )
        }
    )
    inv = fetch_sitemap(
        f, TARGET, "User-agent: *\nSitemap: https://8.8.8.8/custom-sitemap.xml"
    )
    assert inv.ok is True
    assert inv.urls == ["https://8.8.8.8/a-vs-b"]


def test_unreadable_sitemap_reports_not_ok():
    inv = fetch_sitemap(FakeFetcher({}), TARGET)
    assert inv.ok is False and inv.urls == []
    assert inv.evidence[0].status == 404


def test_evidence_records_transport_failure_with_no_status():
    class Boom(FakeFetcher):
        def get(self, url):
            raise TimeoutError("timed out")

    p = probe(Boom({}), TARGET)
    assert p.failed is True
    assert p.evidence.status is None
    assert "TimeoutError" in (p.evidence.note or "")


def _ctx() -> DiagnosisContext:
    return DiagnosisContext(
        account_id=uuid.uuid4(), brand_name="Acme", target_url=TARGET
    )


def test_evidence_model_roundtrips():
    e = Evidence(url="u", status=200, fetched_at="2026-01-01T00:00:00+00:00")
    assert e.model_dump()["status"] == 200


# ── noindex: the most severe defect must outrank everything ──────────────
NOINDEX_PAGE = FetchResult(
    url=TARGET,
    final_url=TARGET,
    status=200,
    ok=True,
    text=(
        '<html><head><meta name="robots" content="noindex, nofollow">'
        "</head><body><h2>hi</h2></body></html>"
    ),
)


def test_noindex_is_reported_as_a_gap():
    """It used to be detected at severity high and silently dropped: no
    gap_type meant it never reached the report or the planner."""
    from app.pipeline.diagnosis.seo import check_seo

    noindex = next(f for f in check_seo(NOINDEX_PAGE) if f.code == "noindex")
    assert noindex.gap_type == "page_noindex"
    assert noindex.severity == "urgent"
    assert noindex.confidence == 1.0
    gap = finding_to_gap(noindex)
    assert gap is not None and gap.fix_type == "remove_noindex"


def test_noindex_outranks_every_other_gap():
    from app.pipeline.diagnosis.seo import check_seo

    gaps = findings_to_gaps(check_seo(NOINDEX_PAGE))
    assert gaps[0].gap_type == "page_noindex"
    assert gaps[0].rank_score == 1.0

    items = plan(
        [
            GapInput(
                gap_id=uuid.uuid4(),
                gap_type=g.gap_type,
                fix_type=g.fix_type,
                prompt_ids=[],
                details=g.details,
            )
            for g in gaps
        ]
    ).items
    assert items[0].fix_type == "remove_noindex"
    assert items[0].score == 1.0


def test_single_page_schema_absence_is_below_the_ranking_floor():
    """add_schema_markup is a site-wide fix; one page can't justify it."""
    from app.pipeline.diagnosis.seo import check_seo

    schema = next(f for f in check_seo(NOINDEX_PAGE) if f.code == "schema_missing")
    assert schema.confidence < 0.5
    assert schema.detail["fix_scope"] == "site_wide"

    gap = finding_to_gap(schema)
    assert gap is not None, "still stored and reported"
    ranked = plan(
        [
            GapInput(
                gap_id=uuid.uuid4(),
                gap_type=gap.gap_type,
                fix_type=gap.fix_type,
                prompt_ids=[],
                details=gap.details,
            )
        ]
    ).items
    assert ranked == [], "but never ranked on one page's evidence"


# ── stale_content: advisory, reported, never the top recommendation ──────
NO_DATE_PAGE = FetchResult(
    url=TARGET,
    final_url=TARGET,
    status=200,
    ok=True,
    text="<html><body><h1>Acme</h1><p>No dates anywhere.</p></body></html>",
)
DATED_PAGE = FetchResult(
    url=TARGET,
    final_url=TARGET,
    status=200,
    ok=True,
    text="<html><body><h1>Acme</h1><time>2026-07-01</time></body></html>",
)


def test_missing_freshness_signal_is_now_reported_as_a_gap():
    """It used to be detected (ok=False) with no gap_type — invisible."""
    from app.pipeline.diagnosis.seo import check_seo

    f = next(f for f in check_seo(NO_DATE_PAGE) if f.code == "no_freshness_signal")
    assert f.ok is False
    assert f.gap_type == "stale_content"
    assert f.severity == "low"
    gap = finding_to_gap(f)
    assert gap is not None and gap.fix_type == "add_freshness_signals"


def test_freshness_present_produces_no_gap():
    from app.pipeline.diagnosis.seo import check_seo

    f = next(f for f in check_seo(DATED_PAGE) if f.code == "freshness_signal")
    assert f.ok is True and f.gap_type is None
    assert finding_to_gap(f) is None


def test_stale_content_is_reported_but_not_ranked():
    """Advisory + single-page inference: it belongs in the report, never as the
    headline fix."""
    from app.pipeline.diagnosis.seo import check_seo

    f = next(f for f in check_seo(NO_DATE_PAGE) if f.code == "no_freshness_signal")
    assert f.confidence < 0.5
    gap = finding_to_gap(f)
    assert gap is not None
    ranked = plan(
        [
            GapInput(
                gap_id=uuid.uuid4(),
                gap_type=gap.gap_type,
                fix_type=gap.fix_type,
                prompt_ids=[],
                details=gap.details,
            )
        ]
    ).items
    assert ranked == []
