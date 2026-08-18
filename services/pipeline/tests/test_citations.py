# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Citation-list checks (audit finding A15).

The defect: `check_third_party_presence` fetched every cited URL and grepped it
for the brand. Gemini's grounded citations are `vertexaisearch.cloud.google.com/
grounding-api-redirect/...` wrappers, so the fetch read a redirect rather than a
publisher — and `seen_on == 0` then emitted a HIGH-severity
`missing_from_listicles` gap. A confident accusation built on pages never read.

The rule these tests pin is the one the truncation and sitemap work already
follow: **never assert an absence you did not establish.** Concretely —

  * domain-level questions are answered from the citation list alone, so they
    cannot fail on an unfetchable URL;
  * anything requiring the page BODY degrades to `check_failed`, never a gap,
    when nothing could actually be read.
"""

from __future__ import annotations

import uuid

import pytest

from app.pipeline.diagnosis.citations import (
    check_cited_domains,
    is_redirect_wrapper,
    registrable_domain,
    resolvable_sources,
)
from app.pipeline.diagnosis.contracts import CitedSource, DiagnosisContext
from app.pipeline.diagnosis.fetcher import FakeFetcher, FetchResult
from app.pipeline.diagnosis.geo import check_third_party_presence

WRAPPER = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQF3n2xK"


def _ctx(sources: list[CitedSource] | None = None, **over) -> DiagnosisContext:
    base = dict(
        account_id=uuid.uuid4(),
        scan_id=uuid.uuid4(),
        brand_name="Imagine Art",
        brand_aliases=["ImagineArt"],
        target_url="https://www.imagine.art/",
        cited_sources=sources or [],
    )
    base.update(over)
    return DiagnosisContext(**base)


# ── domain parsing ───────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.imagine.art/pricing", "imagine.art"),
        ("https://imagine.art", "imagine.art"),
        ("https://blog.sub.example.com/x", "example.com"),
        ("https://www.example.co.uk/x", "example.co.uk"),
        ("https://a.b.example.com.au/", "example.com.au"),
        ("not a url", None),
        ("", None),
    ],
)
def test_registrable_domain(url, expected):
    assert registrable_domain(url) == expected


def test_gemini_grounding_redirects_are_recognised_as_wrappers():
    assert is_redirect_wrapper(WRAPPER) is True
    # Caught by path shape too, so a NEW grounding host needs no list update.
    assert is_redirect_wrapper("https://unknown.example/grounding-api-redirect/x")
    assert is_redirect_wrapper("https://www.imagine.art/blogs/x") is False


def test_resolvable_sources_drops_only_wrappers():
    sources = [
        CitedSource(url=WRAPPER),
        CitedSource(url="https://zapier.com/blog/x", title="Best tools"),
    ]
    assert [s.url for s in resolvable_sources(sources)] == ["https://zapier.com/blog/x"]


# ── the check that cannot lie ────────────────────────────────────────────
def test_all_wrappers_is_check_failed_not_a_gap():
    """THE A15 REGRESSION. Every citation is a redirect, so the publishers were
    never identified. The old code called this 'absent from third-party pages'
    at HIGH severity."""
    finding = check_cited_domains(_ctx([CitedSource(url=WRAPPER)] * 3))

    assert finding.status == "check_failed"
    assert finding.confidence == 0.0
    assert finding.gap_type is None, "a check that read nothing must not raise a gap"
    assert "redirect wrappers" in finding.summary
    assert finding.detail["citations_readable"] == 0
    assert "vertexaisearch.cloud.google.com" in finding.detail["redirect_wrapper_hosts"]


def test_absent_from_readable_citations_is_a_real_gap():
    """With real publisher URLs the claim IS established: none of them is ours."""
    finding = check_cited_domains(
        _ctx(
            [
                CitedSource(url="https://zapier.com/blog/a", title="Best AI tools"),
                CitedSource(url="https://www.techradar.com/b", title="Top generators"),
                CitedSource(url="https://zapier.com/blog/c"),
            ]
        )
    )

    assert finding.status == "confirmed_absent"
    assert finding.gap_type == "missing_from_listicles"
    assert finding.from_absence is True
    assert finding.detail["own_domain"] == "imagine.art"
    assert finding.detail["self_citations"] == 0
    assert finding.detail["distinct_domains"] == 2
    # The domain histogram is the auditable basis for the verdict.
    assert finding.detail["top_domains"][0] == {"domain": "zapier.com", "citations": 2}
    # Publisher titles are carried through, so a report can show WHAT was cited.
    assert any(
        e["title"] == "Best AI tools" for e in finding.detail["third_party_examples"]
    )


def test_self_citation_is_a_pass_with_a_count():
    finding = check_cited_domains(
        _ctx(
            [
                CitedSource(url="https://www.imagine.art/blogs/x"),
                CitedSource(url="https://zapier.com/blog/a"),
            ]
        )
    )
    assert finding.ok is True
    assert finding.status == "confirmed_present"
    assert finding.gap_type is None
    assert finding.detail["self_citations"] == 1


def test_mixed_wrappers_still_judge_on_what_was_readable():
    finding = check_cited_domains(
        _ctx([CitedSource(url=WRAPPER), CitedSource(url="https://zapier.com/b")])
    )
    assert finding.status == "confirmed_absent"
    assert finding.detail["citations_wrapped"] == 1
    assert finding.detail["citations_readable"] == 1


def test_no_citations_produces_no_finding():
    """A scan with no citations is the monitor's business to report, not a site
    defect. Inventing a gap here would blame the customer for our own gap."""
    assert check_cited_domains(_ctx([])) is None


# ── the body check, now conditional ──────────────────────────────────────
def test_body_check_refuses_to_judge_wrapper_only_citations():
    finding = check_third_party_presence(
        FakeFetcher({}), _ctx([CitedSource(url=WRAPPER)]), max_pages=5
    )
    assert finding.status == "check_failed"
    assert finding.gap_type is None
    assert finding.detail["redirect_wrapped"] == 1


def test_body_check_reports_check_failed_when_every_fetch_fails():
    """A page we could not fetch is not a page without our brand in it."""
    ctx = _ctx([CitedSource(url="https://zapier.com/blog/a")])
    finding = check_third_party_presence(FakeFetcher({}), ctx, max_pages=5)

    assert finding.status == "check_failed"
    assert finding.gap_type is None
    assert finding.detail["pages_read"] == 0


def test_body_check_raises_a_gap_only_on_pages_it_actually_read():
    url = "https://zapier.com/blog/a"
    fetcher = FakeFetcher(
        {
            url: FetchResult(
                url=url,
                final_url=url,
                status=200,
                ok=True,
                text="<html>Midjourney and DALL-E are great.</html>",
            )
        }
    )
    finding = check_third_party_presence(
        fetcher, _ctx([CitedSource(url=url)]), max_pages=5
    )

    assert finding.status == "confirmed_absent"
    assert finding.gap_type == "missing_from_listicles"
    assert finding.detail["pages_read"] == 1
    assert finding.detail["brand_seen_on"] == 0


def test_body_check_passes_when_the_brand_is_on_the_page():
    url = "https://zapier.com/blog/a"
    fetcher = FakeFetcher(
        {
            url: FetchResult(
                url=url,
                final_url=url,
                status=200,
                ok=True,
                text="<html>Try ImagineArt for video.</html>",
            )
        }
    )
    finding = check_third_party_presence(
        fetcher, _ctx([CitedSource(url=url)]), max_pages=5
    )
    assert finding.ok is True
    assert finding.detail["brand_seen_on"] == 1


def test_a_non_200_page_counts_as_unread_not_as_absence():
    url = "https://zapier.com/blog/a"
    fetcher = FakeFetcher(
        {url: FetchResult(url=url, final_url=url, status=403, ok=False, text="")}
    )
    finding = check_third_party_presence(
        fetcher, _ctx([CitedSource(url=url)]), max_pages=5
    )
    assert finding.status == "check_failed"
    assert finding.gap_type is None
    assert "HTTP 403" in finding.detail["unreadable"][0]
