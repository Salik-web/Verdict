# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""SEO checks (the floor): structured data, heading structure, indexability,
freshness, and a page-weight signal. Deterministic HTML parsing — no LLM.

EVERY check here examines exactly ONE page (the entry URL), so every summary
names that URL. "No structured data found" reads as a statement about the site
and is not one — a marketing site can carry schema on its product pages and none
on an app-shell homepage. Phrasing the scope honestly is what stops a page-level
observation being read as a site-wide verdict.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from app.pipeline.diagnosis.contracts import Evidence, Finding
from app.pipeline.diagnosis.fetcher import FetchResult

# A conclusion drawn from ONE page whose fix is site-wide. Deliberately below the
# planner's floor: "this page has no schema" is real, but it does not establish
# that the SITE needs schema work, so it is stored and reported yet can never
# become the top recommendation on one page's evidence.
_SINGLE_PAGE_INFERENCE_CONFIDENCE = 0.4


def _where(page: FetchResult) -> str:
    """The URL actually examined (after redirects)."""
    return page.final_url or page.url


def check_seo(
    page: FetchResult, evidence: list[Evidence] | None = None
) -> list[Finding]:
    """Deterministic checks on ONE fetched page. Every finding carries the
    evidence for that page, and names the URL it is about — these are page-level
    facts, never site-wide claims."""
    ev = list(evidence or [])
    url = _where(page)
    soup = BeautifulSoup(page.text or "", "lxml")
    findings: list[Finding] = []

    # Structured data (JSON-LD or microdata).
    has_jsonld = bool(soup.find("script", attrs={"type": "application/ld+json"}))
    has_microdata = bool(soup.find(attrs={"itemscope": True}))
    if has_jsonld or has_microdata:
        findings.append(
            Finding(
                layer="seo",
                code="schema_present",
                ok=True,
                severity="info",
                summary=f"Structured data present on {url}.",
                evidence=ev,
                detail={"page_url": url},
            )
        )
    else:
        findings.append(
            Finding(
                layer="seo",
                code="schema_missing",
                ok=False,
                severity="medium",
                summary=(
                    f"No structured data (JSON-LD / schema.org) on {url} — "
                    "checked this page only."
                ),
                gap_type="missing_schema",
                status="confirmed_absent",
                # add_schema_markup is a site-wide fix; one page can't justify it.
                confidence=_SINGLE_PAGE_INFERENCE_CONFIDENCE,
                evidence=ev,
                detail={
                    "page_url": url,
                    "scope": "single_page",
                    "fix_scope": "site_wide",
                },
            )
        )

    # Heading structure — expect exactly one H1.
    h1s = soup.find_all("h1")
    if len(h1s) == 1:
        findings.append(
            Finding(
                layer="seo",
                code="headings_ok",
                ok=True,
                severity="info",
                summary=f"Single H1 with heading structure on {url}.",
                evidence=ev,
                detail={"page_url": url},
            )
        )
    else:
        findings.append(
            Finding(
                layer="seo",
                code="weak_headings",
                ok=False,
                severity="low",
                summary=(
                    f"Expected one H1, found {len(h1s)} on "
                    f"{page.final_url or page.url} — weak structure."
                ),
                gap_type="weak_page_structure",
                status="confirmed_absent",
                evidence=ev,
                detail={
                    "h1_count": len(h1s),
                    "page_url": url,
                    "scope": "single_page",
                },
            )
        )

    # Indexability — a page-level noindex hides you from search entirely.
    robots_meta = soup.find(
        "meta", attrs={"name": lambda v: v and v.lower() == "robots"}
    )
    content = (robots_meta.get("content", "") if robots_meta else "").lower()
    if "noindex" in content:
        findings.append(
            Finding(
                layer="seo",
                code="noindex",
                ok=False,
                severity="urgent",
                summary=(
                    f"{url} has meta robots noindex — engines are told not to "
                    "index it, so nothing else in this report can help until "
                    "it is removed."
                ),
                gap_type="page_noindex",
                status="confirmed_absent",
                # Definitive: the tag is either in the HTML we fetched or it is
                # not. The fix is on this exact page, so no inference discount.
                confidence=1.0,
                # The only finding here backed by something we FOUND rather than
                # by something we failed to find — so a truncated page does not
                # weaken it. (The tag is in <head>, well inside any byte cap.)
                from_absence=False,
                evidence=ev,
                detail={
                    "page_url": url,
                    "scope": "single_page",
                    "robots_meta": content,
                },
            )
        )

    # Freshness signal (informational; no direct gap type).
    has_date = bool(
        soup.find("time")
        or soup.find("meta", attrs={"property": "article:modified_time"})
        or page.headers.get("last-modified")
    )
    findings.append(
        Finding(
            layer="seo",
            code="freshness_signal" if has_date else "no_freshness_signal",
            ok=has_date,
            severity="info" if has_date else "low",
            summary=(
                f"Freshness signal present on {url}."
                if has_date
                else (
                    f"No freshness signal (published/updated date) on {url} — "
                    "engines can't tell how current this content is."
                )
            ),
            gap_type=None if has_date else "stale_content",
            # Same shape as missing_schema: one page's absence of a date does not
            # establish that the SITE's content is undated, and the fix is
            # editorial across templates — so it is reported but never ranked as
            # the top recommendation on this evidence alone.
            confidence=1.0 if has_date else _SINGLE_PAGE_INFERENCE_CONFIDENCE,
            evidence=ev,
            detail={
                "page_url": url,
                "scope": "single_page",
                **({} if has_date else {"fix_scope": "site_wide"}),
            },
        )
    )

    # Page-weight signal (crude page-speed proxy).
    kb = len((page.text or "").encode("utf-8", "ignore")) // 1024
    blocking = len(soup.select("head script:not([async]):not([defer])"))
    findings.append(
        Finding(
            layer="seo",
            code="page_weight",
            ok=kb < 500,
            severity="info",
            summary=(f"{url}: HTML ~{kb} KB, {blocking} blocking head scripts."),
            evidence=ev,
            detail={
                "html_kb": kb,
                "blocking_head_scripts": blocking,
                "page_url": url,
                "scope": "single_page",
            },
        )
    )
    return findings
