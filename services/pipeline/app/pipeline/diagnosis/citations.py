# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""What the engines actually cited — answered from the citation list alone.

Audit finding A15. `check_third_party_presence` fetched every cited URL and
grepped it for the brand name. Two independent things made that dead code:

  1. The pipeline chain never populated `competitor_urls`, so the check returned
     None on every real scan.
  2. Gemini's grounded citations are `vertexaisearch.cloud.google.com/
     grounding-api-redirect/...` wrappers, not publisher URLs. Fetching one
     tells you nothing about the article behind it — yet `seen_on == 0` emitted
     a HIGH-severity `missing_from_listicles` gap. A confident accusation built
     on pages we never read.

The fix is to narrow the claim to what the data supports, rather than to fetch
harder. Titles and domains cannot answer "is my brand in the body of that
page?" — a listicle headed "9 Best Midjourney Alternatives" won't say
"ImagineArt" in its title even when ImagineArt is first in the body. Body
presence genuinely needs the body.

But the citation list alone answers three things exactly, with no HTTP and no
way to be wrong:

  * which domains the engines cite — the pages actually shaping answers about you
  * whether the engines ever cite YOUR domain (self-citation)
  * whether your domain is absent from that set

That last one is a real, checkable gap. This module computes it, and refuses to
compute it when the citations are redirect wrappers whose real domain we never
saw — same rule the truncation and sitemap work already follow: never assert an
absence you did not establish.
"""

from __future__ import annotations

from collections import Counter
from urllib.parse import urlparse

from app.pipeline.diagnosis.contracts import CitedSource, DiagnosisContext, Finding

# Hosts that wrap a real destination behind a redirect. A citation on one of
# these carries NO information about the publisher, so it cannot support either
# "your brand is present" or "your brand is absent".
#
# Gemini's grounding API is the one we hit in production; the others are listed
# because the same shape appears whenever an engine proxies its sources.
REDIRECT_WRAPPER_HOSTS = frozenset(
    {
        "vertexaisearch.cloud.google.com",
        "grounding-api-redirect.googleapis.com",
        "www.google.com",  # /url?q= interstitials
        "duckduckgo.com",  # /l/?uddg= interstitials
    }
)

# Two-label public suffixes common enough to matter. Not a full Public Suffix
# List — pulling one in for this would be a dependency and a data-refresh
# problem for a check whose worst failure is grouping two subdomains together.
_MULTI_PART_SUFFIXES = frozenset(
    {
        "co.uk",
        "org.uk",
        "ac.uk",
        "gov.uk",
        "com.au",
        "net.au",
        "org.au",
        "co.nz",
        "co.jp",
        "co.in",
        "co.za",
        "com.br",
        "com.mx",
        "com.sg",
    }
)


def registrable_domain(url: str) -> str | None:
    """The domain a citation belongs to: `https://www.a.example.co.uk/x` ->
    `example.co.uk`. Returns None when there is no parseable host."""
    try:
        host = (urlparse(url).hostname or "").lower().strip(".")
    except ValueError:
        return None
    if not host:
        return None
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    last_two = ".".join(labels[-2:])
    if last_two in _MULTI_PART_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return last_two


def is_redirect_wrapper(url: str) -> bool:
    """True when the URL points at a grounding redirect rather than a publisher."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    if host in REDIRECT_WRAPPER_HOSTS:
        return True
    # Path-shaped tell, so a new grounding host is caught without a list update.
    try:
        path = urlparse(url).path.lower()
    except ValueError:
        return False
    return "grounding-api-redirect" in path


def resolvable_sources(sources: list[CitedSource]) -> list[CitedSource]:
    """Citations whose publisher domain we can actually read."""
    return [s for s in sources if not is_redirect_wrapper(s.url)]


def check_cited_domains(context: DiagnosisContext) -> Finding | None:
    """Which domains the engines cited, and whether the customer's is among them.

    Pure: no HTTP. Returns None when the scan produced no citations at all —
    that is the monitor's business to report, not a site defect.
    """
    sources = context.cited_sources
    if not sources:
        return None

    own = registrable_domain(context.target_url)
    wrappers = [s for s in sources if is_redirect_wrapper(s.url)]
    readable = resolvable_sources(sources)

    # Every citation is a redirect wrapper: we never learned a single publisher,
    # so we cannot say the customer is absent from a set we could not see.
    if not readable:
        wrapper_hosts = sorted(
            {urlparse(s.url).hostname or "?" for s in wrappers if s.url}
        )
        return Finding(
            layer="geo",
            code="cited_domains",
            ok=False,
            severity="info",
            status="check_failed",
            confidence=0.0,
            summary=(
                f"All {len(sources)} citation(s) are redirect wrappers "
                f"({', '.join(wrapper_hosts)}), so the publishers behind them were "
                "never identified. No claim is made about who cites you."
            ),
            detail={
                "check": "cited_domains",
                "basis": "citation_list",
                "citations_total": len(sources),
                "citations_readable": 0,
                "redirect_wrapper_hosts": wrapper_hosts,
                "own_domain": own,
            },
        )

    counts = Counter()
    for source in readable:
        domain = registrable_domain(source.url)
        if domain:
            counts[domain] += 1

    top = [{"domain": d, "citations": n} for d, n in counts.most_common(15)]
    self_citations = counts.get(own, 0) if own else 0
    # Titles are carried through so a reader can see WHAT was cited, not just
    # where from — this is the field Perplexity supplies and Gemini does not.
    examples = [
        {"url": s.url, "title": s.title}
        for s in readable[:10]
        if registrable_domain(s.url) != own
    ][:5]

    detail = {
        "check": "cited_domains",
        "basis": "citation_list",
        "citations_total": len(sources),
        "citations_readable": len(readable),
        "citations_wrapped": len(wrappers),
        "distinct_domains": len(counts),
        "own_domain": own,
        "self_citations": self_citations,
        "top_domains": top,
        "third_party_examples": examples,
    }

    if own and self_citations == 0:
        return Finding(
            layer="geo",
            code="cited_domains",
            ok=False,
            severity="medium",
            status="confirmed_absent",
            confidence=1.0,
            from_absence=True,
            gap_type="missing_from_listicles",
            summary=(
                f"{own} is not cited by the engines: {len(readable)} readable "
                f"citation(s) across {len(counts)} domain(s), none of them yours. "
                "The pages shaping answers about you are all third-party."
            ),
            detail=detail,
        )

    return Finding(
        layer="geo",
        code="cited_domains",
        ok=True,
        severity="info",
        status="confirmed_present",
        confidence=1.0,
        summary=(
            f"{own} is cited {self_citations} time(s) across {len(readable)} "
            f"readable citation(s) from {len(counts)} domain(s)."
            if own
            else f"{len(readable)} readable citation(s) from {len(counts)} domain(s)."
        ),
        detail=detail,
    )
