# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Gaps raised by logic that has since been replaced must stop asserting.

Scan c1f854e5 raised `no_owned_comparison_page` at rank 0.810 for imagine.art — a
site with a /compare hub and dozens of comparison URLs. The check looked only at
the homepage's anchors (an app shell that links to none of the marketing pages)
and reported the answer as a site-wide fact. The sitemap-based check replaced it,
but only for NEW scans: that row is still `open`, still 0.810, still eligible for
planning.

The asymmetry these tests pin is the whole design:

  a gap is CLOSED only on a positive disagreement — the current logic ran and
  found no gap;
  a gap is LEFT ALONE when the current logic still raises it, AND when the
  re-check could not conclude at all.

Dismissing a customer's real gap because our own fetch failed would be the
original bug with the sign flipped.
"""

from __future__ import annotations

import uuid

import pytest

from app.pipeline.diagnosis.fetcher import FakeFetcher, Fetcher, FetchResult
from app.pipeline.diagnosis.revalidate import (
    DIAGNOSIS_LOGIC_VERSION,
    INCONCLUSIVE,
    NO_LONGER_RAISED,
    NOT_RECHECKABLE,
    STILL_RAISED,
    revalidate_gap,
)

SITE = "https://example.com"
GAP_ID = uuid.uuid4()
HOME = "<html><body><div id='root'></div></body></html>"


def _page(url: str, body: str, ctype: str) -> FetchResult:
    return FetchResult(
        url=url,
        final_url=url,
        status=200,
        ok=True,
        text=body,
        headers={"content-type": ctype},
        content_type=ctype,
    )


def _fetcher(
    *paths: str, robots: str = "User-agent: *\nDisallow:\n", site: str = SITE
) -> FakeFetcher:
    locs = "".join(f"<url><loc>{site}{p}</loc></url>" for p in paths)
    return FakeFetcher(
        {
            site: _page(site, HOME, "text/html"),
            f"{site}/": _page(f"{site}/", HOME, "text/html"),
            f"{site}/robots.txt": _page(f"{site}/robots.txt", robots, "text/plain"),
            f"{site}/sitemap.xml": _page(
                f"{site}/sitemap.xml",
                f"<?xml version='1.0'?><urlset>{locs}</urlset>",
                "application/xml",
            ),
        }
    )


def _check(fetcher: Fetcher, *, gap_type="no_owned_comparison_page", url=SITE):
    return revalidate_gap(
        gap_id=GAP_ID,
        gap_type=gap_type,
        scan_id=uuid.uuid4(),
        rank_score=0.810,
        status="open",
        target_url=url,
        fetcher=fetcher,
    )


class _ExplodingFetcher(Fetcher):
    def get(self, url: str) -> FetchResult:
        raise RuntimeError("connection reset by peer")


# ── DB fixtures for the write path ───────────────────────────────────────
# `revalidate_stored_gaps` resolves the target from the ACCOUNT's domain, and
# FakeFetcher still runs the SSRF guard — so the domain has to be one that
# actually resolves. The seeded demo account's acme.example.com does not, which
# would make every re-check inconclusive for the wrong reason. A throwaway
# account keeps these tests independent of seed data either way.
DB_SITE = "https://8.8.8.8"


@pytest.fixture
def account_with_gap():
    from sqlalchemy.exc import OperationalError

    from app.db.base import SessionLocal
    from app.db.models import Account, Gap

    try:
        with SessionLocal() as s:
            s.connection()
    except OperationalError:
        pytest.skip("database unreachable")

    suffix = uuid.uuid4().hex[:8]
    with SessionLocal() as s:
        account = Account(
            name=f"revalidate-test-{suffix}",
            slug=f"revalidate-test-{suffix}",
            domain="8.8.8.8",
            brand_name="Acme",
        )
        s.add(account)
        s.flush()
        gap = Gap(
            account_id=account.id,
            gap_type="no_owned_comparison_page",
            details={"fix_type": "generate_comparison_page", "summary": "pre-fix"},
            rank_score=0.810,
            status="open",
        )
        s.add(gap)
        s.commit()
        account_id, gap_id = account.id, gap.id

    yield account_id, gap_id

    with SessionLocal() as s:
        # Cascade removes the gap with the account.
        s.delete(s.get(Account, account_id))
        s.commit()


# ── the case that motivated this ─────────────────────────────────────────
def test_a_pre_fix_false_gap_is_closed():
    """imagine.art in miniature: comparison pages exist in the sitemap and are
    linked from nowhere on the homepage."""
    result = _check(_fetcher("/", "/pricing", "/compare/us-vs-them"))
    assert result.verdict == NO_LONGER_RAISED
    assert result.closes is True
    assert "current logic finds no gap" in result.reason
    # The dismissal carries the new check's working, so it is as checkable as the
    # finding it retires.
    assert result.detail["basis"] == "sitemap"
    assert result.detail["matches"] == 1


# ── the two "leave it alone" paths ───────────────────────────────────────
def test_a_gap_the_current_logic_still_raises_is_untouched():
    result = _check(_fetcher("/", "/pricing", "/about"))
    assert result.verdict == STILL_RAISED
    assert result.closes is False
    assert result.detail["matches"] == 0


def test_an_unreachable_site_does_not_close_the_gap():
    """ "We couldn't check" is not evidence the finding was wrong.

    The transport error surfaces as an unreadable sitemap rather than a raised
    exception — `probe` converts every transport failure into a recorded
    non-result on purpose. Either way the verdict must be inconclusive.
    """
    result = _check(_ExplodingFetcher())
    assert result.verdict == INCONCLUSIVE
    assert result.closes is False
    assert result.detail["sitemap_readable"] is False
    # status None (not 404) is the signature of "we never got a response".
    assert result.detail["sitemap"]["documents"][0]["status"] is None


def test_an_unreadable_sitemap_is_inconclusive_in_both_directions():
    """Falling back to homepage anchors is EXACTLY the logic that produced the
    false gap. It must not retire a stored finding, and it must not confirm one
    either — judging the old evidence by the old evidence is circular."""
    bare = FakeFetcher(
        {
            f"{SITE}/": _page(f"{SITE}/", HOME, "text/html"),
            f"{SITE}/robots.txt": _page(
                f"{SITE}/robots.txt", "User-agent: *\nDisallow:\n", "text/plain"
            ),
        }
    )
    result = _check(bare)
    assert result.verdict == INCONCLUSIVE
    assert result.detail["sitemap_readable"] is False
    assert result.closes is False


def test_an_empty_sitemap_proves_nothing():
    """Readable but declaring no URLs: there is nothing to have searched, so
    "no comparison page found" would be vacuous."""
    result = _check(_fetcher())  # a valid <urlset> with zero <url> entries
    assert result.verdict == INCONCLUSIVE
    assert result.detail["sitemap_urls_read"] == 0
    assert result.closes is False


def test_a_gap_type_with_no_recheck_is_not_touched():
    result = _check(_fetcher("/"), gap_type="missing_llms_txt")
    assert result.verdict == NOT_RECHECKABLE
    assert result.closes is False


def test_an_account_with_no_domain_is_inconclusive():
    result = _check(_fetcher("/"), url=None)
    assert result.verdict == INCONCLUSIVE
    assert "no domain" in result.reason
    assert result.closes is False


# ── the write path ───────────────────────────────────────────────────────
def test_apply_dismisses_rather_than_resolves(account_with_gap):
    """`resolved` would claim the customer fixed something they never had."""
    from app.db.base import SessionLocal
    from app.db.models import Gap
    from app.pipeline.diagnosis.revalidate import revalidate_stored_gaps

    account_id, gap_id = account_with_gap
    with SessionLocal() as s:
        results = revalidate_stored_gaps(
            s,
            account_id,
            apply=True,
            fetcher=_fetcher("/", "/compare/us-vs-them", site=DB_SITE),
        )
        s.commit()
    assert [r.verdict for r in results] == [NO_LONGER_RAISED]

    with SessionLocal() as s:
        row = s.get(Gap, gap_id)
        assert row.status == "dismissed"
        rv = row.details["revalidation"]
        assert rv["logic_version"] == DIAGNOSIS_LOGIC_VERSION
        assert rv["verdict"] == NO_LONGER_RAISED
        assert rv["previous_status"] == "open"
        assert rv["basis"]["matches"] == 1
        # The original details survive — a correction, not an erasure.
        assert row.details["fix_type"] == "generate_comparison_page"
        assert row.details["summary"] == "pre-fix"


def test_report_only_writes_nothing(account_with_gap):
    from app.db.base import SessionLocal
    from app.db.models import Gap
    from app.pipeline.diagnosis.revalidate import revalidate_stored_gaps

    account_id, gap_id = account_with_gap
    with SessionLocal() as s:
        results = revalidate_stored_gaps(
            s,
            account_id,
            apply=False,
            fetcher=_fetcher("/", "/compare/a-vs-b", site=DB_SITE),
        )
        s.commit()

    assert any(r.closes for r in results)
    with SessionLocal() as s:
        row = s.get(Gap, gap_id)
        assert row.status == "open"
        assert "revalidation" not in (row.details or {})


def test_a_still_raised_gap_is_left_exactly_as_it_was(account_with_gap):
    from app.db.base import SessionLocal
    from app.db.models import Gap
    from app.pipeline.diagnosis.revalidate import revalidate_stored_gaps

    account_id, gap_id = account_with_gap
    with SessionLocal() as s:
        results = revalidate_stored_gaps(
            s, account_id, apply=True, fetcher=_fetcher("/", "/pricing", site=DB_SITE)
        )
        s.commit()
    assert [r.verdict for r in results] == [STILL_RAISED]

    with SessionLocal() as s:
        row = s.get(Gap, gap_id)
        assert row.status == "open"
        assert "revalidation" not in row.details


def test_an_inconclusive_recheck_leaves_the_gap_open(account_with_gap):
    """The asymmetry, end to end: a re-check we could not complete never closes
    a customer's gap."""
    from app.db.base import SessionLocal
    from app.db.models import Gap
    from app.pipeline.diagnosis.revalidate import revalidate_stored_gaps

    account_id, gap_id = account_with_gap
    with SessionLocal() as s:
        results = revalidate_stored_gaps(
            s, account_id, apply=True, fetcher=_ExplodingFetcher()
        )
        s.commit()
    assert [r.verdict for r in results] == [INCONCLUSIVE]

    with SessionLocal() as s:
        assert s.get(Gap, gap_id).status == "open"


def test_dismissed_gaps_are_not_re_examined(account_with_gap):
    """A dismissed row is history. Re-walking it every run would churn the record
    and could flip a closed finding back open on a bad network day."""
    from app.db.base import SessionLocal
    from app.db.models import Gap
    from app.pipeline.diagnosis.revalidate import revalidate_stored_gaps

    account_id, gap_id = account_with_gap
    with SessionLocal() as s:
        s.get(Gap, gap_id).status = "dismissed"
        s.commit()

    with SessionLocal() as s:
        results = revalidate_stored_gaps(
            s, account_id, apply=True, fetcher=_fetcher("/", site=DB_SITE)
        )
        s.commit()
    assert results == []
