# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Sitemap discovery — site-wide URL inventory without crawling.

The comparison-page check used to inspect only the homepage's anchors and report
the answer as a site-wide fact. For a site whose homepage is an app shell that is
simply wrong: when this was written imagine.art had 51 comparison URLs and a
server-rendered /compare hub, none of them linked from the homepage. (It had 93
by 2026-08-17 — the exact number is not the point, and will be stale whenever you
read this; the point is that the homepage never showed any of them.)

A sitemap is the polite, standard way to ask a site what pages it has: it is
advertised in robots.txt (which we already fetch), it is one request, and it
needs no JS. We read the location from robots.txt when present and fall back to
/sitemap.xml. Sitemap-index documents are followed, bounded by max_children so a
huge site can't turn one check into hundreds of fetches.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse, urlunparse

from app.pipeline.diagnosis.contracts import Evidence
from app.pipeline.diagnosis.fetcher import Fetcher
from app.pipeline.diagnosis.probe import probe

_LOC_RE = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.IGNORECASE | re.DOTALL)
_SITEMAP_DIRECTIVE_RE = re.compile(r"(?im)^\s*sitemap:\s*(\S+)\s*$")
_IS_INDEX_RE = re.compile(r"<sitemapindex", re.IGNORECASE)


class SitemapInventory:
    """URLs a site declares it has. `ok=False` means we could not read one, which
    must NOT be treated as 'the site has no such pages'.

    `trail` is the audit record of HOW the inventory was obtained — which
    robots.txt directives were found, which documents were fetched and with what
    status, whether it was a sitemap index. A verdict is only as checkable as its
    basis, and until this existed a correct "no gap here" was exactly as opaque as
    a wrong one: the record kept the conclusion and threw away the working.
    """

    def __init__(
        self,
        urls: list[str],
        evidence: list[Evidence],
        ok: bool,
        trail: dict | None = None,
    ) -> None:
        self.urls = urls
        self.evidence = evidence
        self.ok = ok
        self.trail = trail or {}

    def matching(self, pattern: re.Pattern[str]) -> list[str]:
        return [u for u in self.urls if pattern.search(u.lower())]


def sitemap_urls_from_robots(robots_text: str) -> list[str]:
    return _SITEMAP_DIRECTIVE_RE.findall(robots_text or "")


def default_sitemap_url(target_url: str) -> str:
    p = urlparse(target_url)
    return urlunparse((p.scheme, p.netloc, "/sitemap.xml", "", "", ""))


def fetch_sitemap(
    fetcher: Fetcher,
    target_url: str,
    robots_text: str = "",
    *,
    max_children: int = 5,
    max_urls: int = 5000,
) -> SitemapInventory:
    """Return the site's declared URLs. One request, plus at most `max_children`
    if the document is a sitemap index."""
    robots_directives = sitemap_urls_from_robots(robots_text)
    candidates = robots_directives or [default_sitemap_url(target_url)]

    evidence: list[Evidence] = []
    urls: list[str] = []
    any_ok = False
    # Everything a later reader needs to re-walk this decision by hand.
    trail: dict = {
        "robots_fetched": bool(robots_text),
        "robots_sitemap_directives": robots_directives,
        "source": "robots_directive" if robots_directives else "default_guess",
        "candidates_tried": candidates[:2],
        "documents": [],
        "is_index": False,
    }

    for candidate in candidates[:2]:  # robots may advertise several; two is plenty
        p = probe(fetcher, candidate)
        evidence.append(p.evidence)
        doc: dict = {
            "url": candidate,
            "role": "sitemap",
            "status": p.evidence.status,
            "ok": p.present,
            "locs": 0,
        }
        trail["documents"].append(doc)
        if not p.present or p.result is None:
            continue
        any_ok = True
        body = p.result.text or ""
        locs = [_abs(candidate, u) for u in _LOC_RE.findall(body)]
        doc["locs"] = len(locs)

        if _IS_INDEX_RE.search(body):
            # Sitemap index: the <loc>s are child sitemaps, not pages.
            trail["is_index"] = True
            doc["role"] = "sitemap_index"
            doc["children_declared"] = len(locs)
            doc["children_followed"] = min(len(locs), max_children)
            for child in locs[:max_children]:
                cp = probe(fetcher, child)
                evidence.append(cp.evidence)
                child_locs = (
                    _LOC_RE.findall(cp.result.text or "")
                    if cp.present and cp.result is not None
                    else []
                )
                trail["documents"].append(
                    {
                        "url": child,
                        "role": "child_sitemap",
                        "status": cp.evidence.status,
                        "ok": cp.present,
                        "locs": len(child_locs),
                    }
                )
                urls.extend(_abs(child, u) for u in child_locs)
        else:
            urls.extend(locs)

        if urls:
            break

    # De-dupe, preserve order, and cap so a pathological sitemap can't blow memory.
    seen: set[str] = set()
    deduped: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            deduped.append(u)
        if len(deduped) >= max_urls:
            break

    trail["urls_collected"] = len(urls)
    trail["urls_read"] = len(deduped)
    # A cap hit means the inventory is PARTIAL, so "nothing matched" would be an
    # absence we did not finish establishing — same rule as a truncated page.
    trail["capped_at_max_urls"] = len(deduped) >= max_urls
    trail["max_children"] = max_children
    trail["max_urls"] = max_urls

    return SitemapInventory(urls=deduped, evidence=evidence, ok=any_ok, trail=trail)


def _abs(base: str, url: str) -> str:
    return url if url.startswith(("http://", "https://")) else urljoin(base, url)
