# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Every check's basis must be recoverable from the record — passes included.

Diagnosis stored `len(findings)` and nothing else, so when the sitemap-based
comparison check stopped raising a false `no_owned_comparison_page` for
imagine.art, nothing in the record could show WHY: not the sitemap it read, not
the URLs it matched, not whether it fell back to the homepage heuristic. A
correct verdict was exactly as unauditable as a wrong one.

These tests pin the audit trail itself. They are deliberately about the SHAPE of
the record, not just the verdict: a check that reaches the right answer while
recording nothing is the failure being fixed here.
"""

from __future__ import annotations

from app.pipeline.diagnosis.fetcher import FakeFetcher, FetchResult
from app.pipeline.diagnosis.geo import check_owned_comparison_page
from app.pipeline.diagnosis.sitemap import fetch_sitemap

SITE = "https://example.com"
HOME_NO_LINKS = "<html><body><div id='root'></div></body></html>"
HOME_WITH_LINK = '<html><body><a href="/compare/us-vs-them">Compare</a></body></html>'


def _page(url: str, body: str, content_type: str = "text/html") -> FetchResult:
    return FetchResult(
        url=url,
        final_url=url,
        status=200,
        ok=True,
        text=body,
        headers={"content-type": content_type},
        content_type=content_type,
    )


def _sitemap_xml(*paths: str) -> str:
    locs = "".join(f"<url><loc>{SITE}{p}</loc></url>" for p in paths)
    return f"<?xml version='1.0'?><urlset>{locs}</urlset>"


def _home() -> FetchResult:
    return _page(f"{SITE}/", HOME_NO_LINKS)


# ── sitemap discovery ────────────────────────────────────────────────────
def test_trail_records_a_robots_advertised_sitemap():
    fetcher = FakeFetcher(
        {
            f"{SITE}/sitemap-main.xml": _page(
                f"{SITE}/sitemap-main.xml",
                _sitemap_xml("/", "/pricing", "/compare/a-vs-b"),
                "application/xml",
            )
        }
    )
    inv = fetch_sitemap(fetcher, SITE, f"Sitemap: {SITE}/sitemap-main.xml\n")

    assert inv.ok
    trail = inv.trail
    assert trail["robots_fetched"] is True
    assert trail["source"] == "robots_directive"
    assert trail["robots_sitemap_directives"] == [f"{SITE}/sitemap-main.xml"]
    assert trail["urls_read"] == 3
    assert trail["is_index"] is False
    assert trail["documents"] == [
        {
            "url": f"{SITE}/sitemap-main.xml",
            "role": "sitemap",
            "status": 200,
            "ok": True,
            "locs": 3,
        }
    ]


def test_trail_records_the_default_guess_when_robots_advertises_nothing():
    fetcher = FakeFetcher(
        {
            f"{SITE}/sitemap.xml": _page(
                f"{SITE}/sitemap.xml", _sitemap_xml("/"), "application/xml"
            )
        }
    )
    inv = fetch_sitemap(fetcher, SITE, "User-agent: *\nDisallow:\n")
    assert inv.trail["source"] == "default_guess"
    assert inv.trail["robots_sitemap_directives"] == []
    assert inv.trail["candidates_tried"] == [f"{SITE}/sitemap.xml"]


def test_trail_records_each_child_of_a_sitemap_index():
    index = (
        "<?xml version='1.0'?><sitemapindex>"
        f"<sitemap><loc>{SITE}/sm-1.xml</loc></sitemap>"
        f"<sitemap><loc>{SITE}/sm-2.xml</loc></sitemap>"
        "</sitemapindex>"
    )
    fetcher = FakeFetcher(
        {
            f"{SITE}/sitemap.xml": _page(
                f"{SITE}/sitemap.xml", index, "application/xml"
            ),
            f"{SITE}/sm-1.xml": _page(
                f"{SITE}/sm-1.xml", _sitemap_xml("/a", "/b"), "application/xml"
            ),
            # sm-2 is deliberately absent -> 404, and that must be visible.
        }
    )
    inv = fetch_sitemap(fetcher, SITE, "")
    trail = inv.trail

    assert trail["is_index"] is True
    parent = trail["documents"][0]
    assert parent["role"] == "sitemap_index"
    assert parent["children_declared"] == 2
    assert parent["children_followed"] == 2
    children = {d["url"]: d for d in trail["documents"] if d["role"] == "child_sitemap"}
    assert children[f"{SITE}/sm-1.xml"]["ok"] is True
    assert children[f"{SITE}/sm-1.xml"]["locs"] == 2
    # A child we could NOT read is recorded, not silently skipped.
    assert children[f"{SITE}/sm-2.xml"]["ok"] is False
    assert children[f"{SITE}/sm-2.xml"]["status"] == 404


def test_an_unreadable_sitemap_is_not_an_empty_one():
    inv = fetch_sitemap(FakeFetcher({}), SITE, "")
    assert inv.ok is False
    assert inv.urls == []
    assert inv.trail["documents"][0]["status"] == 404


# ── the comparison check's own trail ─────────────────────────────────────
def test_a_pass_records_what_it_matched():
    """The imagine.art case: the check finds comparison pages and raises nothing.
    That "no problem here" has to carry its working."""
    fetcher = FakeFetcher(
        {
            f"{SITE}/sitemap.xml": _page(
                f"{SITE}/sitemap.xml",
                _sitemap_xml(
                    "/", "/pricing", "/compare/us-vs-them", "/blog/a-vs-b", "/about"
                ),
                "application/xml",
            )
        }
    )
    inv = fetch_sitemap(fetcher, SITE, "")
    finding = check_owned_comparison_page(_home(), inv)

    assert finding.ok is True
    assert finding.gap_type is None
    detail = finding.detail
    assert detail["basis"] == "sitemap"
    assert detail["sitemap_urls_read"] == 5
    assert detail["matches"] == 2
    assert sorted(detail["match_examples"]) == [
        f"{SITE}/blog/a-vs-b",
        f"{SITE}/compare/us-vs-them",
    ]
    # The discovery trail rides along, so the whole chain is one record.
    assert detail["sitemap"]["urls_read"] == 5
    assert "5 URLs read" in finding.summary


def test_a_real_absence_records_how_much_was_checked():
    fetcher = FakeFetcher(
        {
            f"{SITE}/sitemap.xml": _page(
                f"{SITE}/sitemap.xml",
                _sitemap_xml("/", "/pricing", "/about"),
                "application/xml",
            )
        }
    )
    finding = check_owned_comparison_page(_home(), fetch_sitemap(fetcher, SITE, ""))
    assert finding.status == "confirmed_absent"
    assert finding.gap_type == "no_owned_comparison_page"
    assert finding.confidence == 1.0
    assert finding.detail["matches"] == 0
    assert finding.detail["sitemap_urls_read"] == 3


def test_the_homepage_fallback_says_why_it_fired():
    """The original false positive came from this path silently. It must now name
    itself and give a reason."""
    finding = check_owned_comparison_page(
        _home(), fetch_sitemap(FakeFetcher({}), SITE, "")
    )
    assert finding.detail["basis"] == "homepage_anchors_only"
    assert finding.detail["fallback_reason"] == "no sitemap document could be read"
    assert finding.detail["sitemap_readable"] is False
    # ...and stays low-confidence, below the planner's floor.
    assert finding.confidence == 0.4


def test_a_homepage_link_rescues_an_empty_sitemap_match():
    fetcher = FakeFetcher(
        {
            f"{SITE}/sitemap.xml": _page(
                f"{SITE}/sitemap.xml", _sitemap_xml("/", "/pricing"), "application/xml"
            )
        }
    )
    finding = check_owned_comparison_page(
        _page(f"{SITE}/", HOME_WITH_LINK), fetch_sitemap(fetcher, SITE, "")
    )
    assert finding.ok is True
    assert finding.detail["basis"] == "sitemap_then_homepage_anchors"


def test_a_capped_inventory_cannot_establish_an_absence():
    """Reading a PREFIX of the sitemap is not reading the sitemap. "Not in the
    first N URLs" is not "not on the site" — same rule as a truncated page."""
    fetcher = FakeFetcher(
        {
            f"{SITE}/sitemap.xml": _page(
                f"{SITE}/sitemap.xml",
                _sitemap_xml(*[f"/p{i}" for i in range(10)]),
                "application/xml",
            )
        }
    )
    inv = fetch_sitemap(fetcher, SITE, "", max_urls=4)
    assert inv.trail["capped_at_max_urls"] is True

    finding = check_owned_comparison_page(_home(), inv)
    assert finding.status == "check_failed"
    assert finding.confidence == 0.0
    assert finding.detail["partial_inventory"] is True
    assert "INCONCLUSIVE" in finding.summary


def test_a_capped_inventory_raises_no_gap():
    from app.pipeline.diagnosis.taxonomy import findings_to_gaps

    fetcher = FakeFetcher(
        {
            f"{SITE}/sitemap.xml": _page(
                f"{SITE}/sitemap.xml",
                _sitemap_xml(*[f"/p{i}" for i in range(10)]),
                "application/xml",
            )
        }
    )
    partial = check_owned_comparison_page(
        _home(), fetch_sitemap(fetcher, SITE, "", max_urls=4)
    )
    complete = check_owned_comparison_page(
        _home(), fetch_sitemap(fetcher, SITE, "", max_urls=100)
    )
    assert findings_to_gaps([partial]) == []
    assert [g.gap_type for g in findings_to_gaps([complete])] == [
        "no_owned_comparison_page"
    ]
