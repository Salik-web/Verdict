"""SEO checks (the floor): structured data, heading structure, indexability,
freshness, and a page-weight signal. Deterministic HTML parsing — no LLM.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from app.pipeline.diagnosis.contracts import Finding
from app.pipeline.diagnosis.fetcher import FetchResult


def check_seo(page: FetchResult) -> list[Finding]:
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
                summary="Structured data present.",
            )
        )
    else:
        findings.append(
            Finding(
                layer="seo",
                code="schema_missing",
                ok=False,
                severity="medium",
                summary="No structured data (JSON-LD / schema.org) found.",
                gap_type="missing_schema",
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
                summary="Single H1 with heading structure.",
            )
        )
    else:
        findings.append(
            Finding(
                layer="seo",
                code="weak_headings",
                ok=False,
                severity="low",
                summary=f"Expected one H1, found {len(h1s)} — weak structure.",
                gap_type="weak_page_structure",
                detail={"h1_count": len(h1s)},
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
                severity="high",
                summary="Page has meta robots noindex — it won't be indexed.",
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
                "Freshness signal present."
                if has_date
                else "No freshness signal (date/modified) found."
            ),
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
            summary=f"HTML ~{kb} KB, {blocking} blocking head scripts.",
            detail={"html_kb": kb, "blocking_head_scripts": blocking},
        )
    )
    return findings
