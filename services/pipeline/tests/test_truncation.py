# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Truncated content cannot establish an absence.

Audit finding #5. Diagnosis recorded `bytes=2000000` — exactly the scraper cap —
for a page that is 2,917,186 bytes. 31% of the document was never analysed and
nothing said so, so "no structured data on this page" was a conclusion about 69%
of a page presented as a conclusion about the page. The verdicts happened to be
right that time; the next one need not be.

The rule is the one diagnosis already applies to a refused fetch: an absence we
could not finish establishing is CHECK_FAILED, never CONFIRMED_ABSENT — and since
only confirmed_absent becomes a Gap, the gap is not raised either.
"""

from __future__ import annotations

import uuid

from app.pipeline.diagnosis.config import ScraperConfig
from app.pipeline.diagnosis.contracts import DiagnosisContext, Evidence, Finding
from app.pipeline.diagnosis.fetcher import FakeFetcher, FetchResult, HttpxFetcher
from app.pipeline.diagnosis.probe import downgrade_truncated_absences, probe
from app.pipeline.diagnosis.seo import check_seo
from app.pipeline.diagnosis.taxonomy import findings_to_gaps

URL = "https://example.com/"


def _evidence(truncated: bool) -> Evidence:
    return Evidence(
        url=URL,
        status=200,
        bytes=2_000_000,
        content_bytes=2_917_186 if truncated else 2_000_000,
        fetched_at="2026-07-28T00:00:00+00:00",
        truncated=truncated,
    )


def _absence(evidence: Evidence) -> Finding:
    return Finding(
        layer="seo",
        code="schema_missing",
        ok=False,
        severity="medium",
        summary=f"No structured data on {URL}.",
        gap_type="missing_schema",
        status="confirmed_absent",
        confidence=0.4,
        evidence=[evidence],
    )


# ── the fetcher records it ───────────────────────────────────────────────
def test_fetcher_flags_a_clipped_response(monkeypatch):
    import httpx

    body = "<html>" + ("x" * 3000) + "</html>"

    class _Resp:
        status_code = 200
        is_redirect = False
        is_success = True
        headers = httpx.Headers({"content-type": "text/html"})
        url = URL
        text = body

    class _Client:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, headers=None):
            return _Resp()

    monkeypatch.setattr(httpx, "Client", _Client)
    cfg = ScraperConfig(user_agent="t", max_bytes=1000)
    result = HttpxFetcher(cfg).get(URL)

    assert result.truncated is True
    assert len(result.text.encode()) <= 1000
    assert result.content_bytes == len(body.encode())


def test_a_complete_response_is_not_flagged(monkeypatch):
    import httpx

    class _Resp:
        status_code = 200
        is_redirect = False
        is_success = True
        headers = httpx.Headers({"content-type": "text/html"})
        url = URL
        text = "<html>small</html>"

    class _Client:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, headers=None):
            return _Resp()

    monkeypatch.setattr(httpx, "Client", _Client)
    result = HttpxFetcher(ScraperConfig(user_agent="t", max_bytes=1_000_000)).get(URL)
    assert result.truncated is False


def test_probe_carries_truncation_into_evidence():
    page = FetchResult(
        url=URL,
        final_url=URL,
        status=200,
        ok=True,
        text="<html></html>",
        truncated=True,
        content_bytes=2_917_186,
    )
    p = probe(FakeFetcher({URL: page}), URL)
    assert p.evidence.truncated is True
    assert p.evidence.content_bytes == 2_917_186
    # The note makes it legible without anyone reading this test.
    assert "clipped" in (p.evidence.note or "")


# ── the downgrade ────────────────────────────────────────────────────────
def test_absence_from_truncated_content_becomes_check_failed():
    [out] = downgrade_truncated_absences([_absence(_evidence(truncated=True))])
    assert out.status == "check_failed"
    assert out.confidence == 0.0
    assert "INCONCLUSIVE" in out.summary
    assert out.detail["analysed_bytes"] == 2_000_000
    assert out.detail["content_bytes"] == 2_917_186


def test_absence_from_a_complete_page_is_untouched():
    finding = _absence(_evidence(truncated=False))
    [out] = downgrade_truncated_absences([finding])
    assert out.status == "confirmed_absent"
    assert out.confidence == 0.4
    assert out == finding


def test_a_downgraded_absence_raises_no_gap():
    """The consequence that matters: no confident recommendation on 69% of a page."""
    truncated = downgrade_truncated_absences([_absence(_evidence(truncated=True))])
    intact = downgrade_truncated_absences([_absence(_evidence(truncated=False))])
    assert findings_to_gaps(truncated) == []
    assert [g.gap_type for g in findings_to_gaps(intact)] == ["missing_schema"]


def test_positive_evidence_survives_truncation():
    """A noindex tag we actually READ stays confirmed — however much of the page
    went unread, finding it is not an absence."""
    page = FetchResult(
        url=URL,
        final_url=URL,
        status=200,
        ok=True,
        text=(
            '<html><head><meta name="robots" content="noindex"></head>'
            "<body></body></html>"
        ),
    )
    findings = check_seo(page, [_evidence(truncated=True)])
    noindex = next(f for f in findings if f.code == "noindex")
    assert noindex.from_absence is False

    [out] = downgrade_truncated_absences([noindex])
    assert out.status == "confirmed_absent"
    assert out.confidence == 1.0
    assert [g.gap_type for g in findings_to_gaps([out])] == ["page_noindex"]


def test_passing_findings_are_never_downgraded():
    ok_finding = Finding(
        layer="seo",
        code="schema_present",
        ok=True,
        severity="info",
        summary="Structured data present.",
        evidence=[_evidence(truncated=True)],
    )
    [out] = downgrade_truncated_absences([ok_finding])
    assert out.status == "confirmed_present"


def test_only_the_findings_that_read_the_truncated_page_are_affected():
    """A 404 on /llms.txt is definitive whatever happened to the homepage."""
    llms = Finding(
        layer="llms_txt",
        code="llms_txt_missing",
        ok=False,
        severity="medium",
        summary="No /llms.txt.",
        gap_type="missing_llms_txt",
        status="confirmed_absent",
        evidence=[
            Evidence(
                url="https://example.com/llms.txt",
                status=404,
                bytes=0,
                fetched_at="2026-07-28T00:00:00+00:00",
            )
        ],
    )
    out = downgrade_truncated_absences([llms, _absence(_evidence(truncated=True))])
    assert out[0].status == "confirmed_absent"
    assert out[1].status == "check_failed"


def test_the_scraper_cap_is_big_enough_for_a_real_marketing_page():
    """The downgrade above is correct but silently drops real findings on heavy
    pages, so the cap has to make truncation the exception. imagine.art's homepage
    (the page that exposed this) is 2,917,186 bytes."""
    from app.pipeline.diagnosis.config import get_diagnosis_config

    assert get_diagnosis_config().scraper.max_bytes >= 2_917_186


def test_diagnosis_context_still_builds():
    # Guard against the contract edits above breaking the stage's input model.
    DiagnosisContext(
        account_id=uuid.uuid4(), brand_name="Acme", target_url="https://acme.test"
    )
