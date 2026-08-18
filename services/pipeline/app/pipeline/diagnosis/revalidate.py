# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Re-check stored GAPS against the current diagnosis logic.

The asset re-validation (execution/revalidate.py) closed the same class of
problem one stage downstream: a record that keeps asserting something the current
code would no longer conclude. This is its counterpart for diagnosis.

The case that motivated it: scan c1f854e5 raised `no_owned_comparison_page` at
rank 0.810 for imagine.art, a site with a /compare hub and dozens of comparison
URLs. The check looked only at the homepage's anchors — an app shell that links to
none of the marketing pages — and reported the answer as a site-wide fact. The
sitemap-based check replaced it, but only for NEW scans: that gap row is still
`open`, still rank 0.810, and still eligible for planning.

RULES, and the second one is the important one:

1. Only gap types with a re-checkable implementation are touched (`_RECHECKS`).
   A gap whose logic hasn't changed is not re-litigated.
2. A gap is closed ONLY when the current logic positively reaches a different
   verdict. If the current logic would still raise it, it is left exactly as it
   is. If the re-check cannot reach a conclusion — the site is unreachable, the
   sitemap is unreadable, the account has no domain — the gap is ALSO left alone.
   "We couldn't check" is not evidence that the finding was wrong, and quietly
   dismissing a customer's real gap because our own network call failed would be
   the same error the check itself was fixed for, in the opposite direction.

Closing uses the existing `dismissed` status: the gap was withdrawn by us, which
is not the same claim as `resolved` (the customer fixed it).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.pipeline.diagnosis.config import get_diagnosis_config
from app.pipeline.diagnosis.contracts import Finding
from app.pipeline.diagnosis.fetcher import Fetcher, FetchResult
from app.pipeline.diagnosis.geo import check_owned_comparison_page
from app.pipeline.diagnosis.probe import probe
from app.pipeline.diagnosis.robots_audit import audit_robots
from app.pipeline.diagnosis.sitemap import fetch_sitemap

# Bump when a check's logic changes in a way that could retire past gaps. Stamped
# onto every row this touches, so "why was this dismissed" has an answer.
# History: absent = homepage-anchors-only comparison check;
# 2026-07-29 = sitemap-based inventory + partial-inventory guard.
DIAGNOSIS_LOGIC_VERSION = "2026-07-29"

STILL_RAISED = "still_raised"  # current logic agrees — left untouched
NO_LONGER_RAISED = "no_longer_raised"  # current logic disagrees — dismissed
INCONCLUSIVE = "inconclusive"  # could not re-check — left untouched
NOT_RECHECKABLE = "not_recheckable"  # no re-check exists for this gap type


@dataclass
class GapRevalidation:
    gap_id: uuid.UUID
    gap_type: str
    scan_id: uuid.UUID | None
    rank_score: float | None
    stored_status: str
    verdict: str
    reason: str
    finding: Finding | None = None
    detail: dict = field(default_factory=dict)

    @property
    def closes(self) -> bool:
        return self.verdict == NO_LONGER_RAISED


def _inconclusive(summary: str, detail: dict) -> Finding:
    return Finding(
        layer="geo",
        code="no_comparison_page",
        ok=False,
        severity="high",
        summary=summary,
        status="check_failed",
        confidence=0.0,
        detail=detail,
    )


def _recheck_comparison_page(fetcher: Fetcher, target_url: str) -> Finding:
    """Re-run the comparison-page check exactly as a live scan would — but refuse
    to judge a stored gap on the evidence that produced it.

    The re-check is only meaningful when the SITEMAP is readable. That is the
    entire substance of the new logic; without it `check_owned_comparison_page`
    falls back to homepage anchors, which is precisely the heuristic that raised
    the false gap in the first place. Letting that fallback confirm — or retire —
    a historical finding would be circular. So an unreadable sitemap, or a
    homepage we never loaded, is INCONCLUSIVE and the gap is left exactly as it is.
    """
    max_pages = get_diagnosis_config().scraper.max_pages_per_scan
    _audit, _findings, robots_text = audit_robots(fetcher, target_url)

    home_probe = probe(fetcher, target_url)
    home = home_probe.result or FetchResult(
        url=target_url,
        final_url=target_url,
        status=home_probe.evidence.status or 0,
        ok=False,
    )
    sitemap = fetch_sitemap(fetcher, target_url, robots_text, max_children=max_pages)

    if not sitemap.ok:
        return _inconclusive(
            "Could not read a sitemap, so the site-wide check could not run — "
            "homepage anchors alone are the heuristic this gap type was fixed for.",
            {"sitemap": dict(sitemap.trail), "sitemap_readable": False},
        )
    if not home_probe.present:
        return _inconclusive(
            f"Could not load {target_url} to re-check.",
            {"home_status": home_probe.evidence.status},
        )
    if not sitemap.urls:
        return _inconclusive(
            "The sitemap was readable but declared no URLs — nothing to check "
            "against.",
            {"sitemap": dict(sitemap.trail), "sitemap_urls_read": 0},
        )
    return check_owned_comparison_page(home, sitemap)


# gap_type -> a callable that re-derives the verdict from the live site.
_RECHECKS = {"no_owned_comparison_page": _recheck_comparison_page}


def revalidate_gap(
    *,
    gap_id: uuid.UUID,
    gap_type: str,
    scan_id: uuid.UUID | None,
    rank_score: float | None,
    status: str,
    target_url: str | None,
    fetcher: Fetcher,
) -> GapRevalidation:
    """Re-derive one gap's verdict. Never raises: a failed re-check is a verdict
    of INCONCLUSIVE, which leaves the gap alone."""

    def result(verdict: str, reason: str, finding=None, detail=None) -> GapRevalidation:
        return GapRevalidation(
            gap_id=gap_id,
            gap_type=gap_type,
            scan_id=scan_id,
            rank_score=rank_score,
            stored_status=status,
            verdict=verdict,
            reason=reason,
            finding=finding,
            detail=detail or {},
        )

    recheck = _RECHECKS.get(gap_type)
    if recheck is None:
        return result(NOT_RECHECKABLE, f"no re-check defined for {gap_type}")
    if not target_url:
        return result(INCONCLUSIVE, "account has no domain to re-check against")

    try:
        finding = recheck(fetcher, target_url)
    except Exception as exc:  # network, SSRF guard, parse — all the same state
        return result(
            INCONCLUSIVE, f"re-check failed: {type(exc).__name__}: {exc}"[:300]
        )

    if finding.status == "check_failed":
        return result(
            INCONCLUSIVE,
            f"current logic could not conclude: {finding.summary}",
            finding,
            dict(finding.detail),
        )
    if finding.ok:
        return result(
            NO_LONGER_RAISED,
            f"current logic finds no gap: {finding.summary}",
            finding,
            dict(finding.detail),
        )
    return result(
        STILL_RAISED,
        f"current logic still raises it: {finding.summary}",
        finding,
        dict(finding.detail),
    )


def revalidate_stored_gaps(
    session,
    account_id: uuid.UUID | None = None,
    *,
    apply: bool = False,
    fetcher: Fetcher | None = None,
) -> list[GapRevalidation]:
    """Re-check every open gap of a re-checkable type (optionally one account's).

    One re-check per (account, gap_type): the verdict is a property of the site as
    it is now, so re-fetching it for each of five historical rows would be five
    times the traffic for the same answer.
    """
    from sqlalchemy import select

    from app.db.models import Account, Gap
    from app.pipeline.diagnosis.stage import default_fetcher

    fetcher = fetcher or default_fetcher()

    stmt = select(Gap).where(
        Gap.gap_type.in_(sorted(_RECHECKS)),
        # Only live gaps. A dismissed or resolved row is history, not a claim.
        Gap.status.in_(("open", "planned")),
    )
    if account_id is not None:
        stmt = stmt.where(Gap.account_id == account_id)
    rows = list(session.scalars(stmt).all())

    urls: dict[uuid.UUID, str | None] = {}
    cache: dict[tuple[uuid.UUID, str], GapRevalidation] = {}
    results: list[GapRevalidation] = []

    for row in rows:
        if row.account_id not in urls:
            account = session.get(Account, row.account_id)
            urls[row.account_id] = (
                f"https://{account.domain}" if account and account.domain else None
            )
        key = (row.account_id, row.gap_type)
        if key in cache:
            base = cache[key]
            outcome = GapRevalidation(
                gap_id=row.id,
                gap_type=row.gap_type,
                scan_id=row.scan_id,
                rank_score=(
                    float(row.rank_score) if row.rank_score is not None else None
                ),
                stored_status=row.status,
                verdict=base.verdict,
                reason=base.reason,
                finding=base.finding,
                detail=base.detail,
            )
        else:
            outcome = revalidate_gap(
                gap_id=row.id,
                gap_type=row.gap_type,
                scan_id=row.scan_id,
                rank_score=(
                    float(row.rank_score) if row.rank_score is not None else None
                ),
                status=row.status,
                target_url=urls[row.account_id],
                fetcher=fetcher,
            )
            cache[key] = outcome
        results.append(outcome)

        if not apply or not outcome.closes:
            continue
        details = dict(row.details or {})
        details["revalidation"] = {
            "at": datetime.now(UTC).isoformat(),
            "logic_version": DIAGNOSIS_LOGIC_VERSION,
            "verdict": outcome.verdict,
            "reason": outcome.reason,
            # The current check's full audit trail, so the dismissal is as
            # checkable as the finding it replaces.
            "basis": outcome.detail,
            "previous_status": row.status,
        }
        # `dismissed`, not `resolved`: WE withdrew the finding. Claiming the
        # customer fixed something they never had would be a different lie.
        row.status = "dismissed"
        row.details = details
    return results
