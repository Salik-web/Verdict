# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""The Diagnosis stage as a LangGraph.

  fetch_home --> run_checks --> map_gaps

`run_checks` runs the robots/bot audit, llms.txt detection, SEO checks, and the
GEO checks (including the mock LLM-as-judge assessment). `map_gaps` turns failing
findings into taxonomy-mapped Gaps. The graph is DB-free and reaches the network
only through the injected Fetcher.
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.gateway import Gateway
from app.pipeline.diagnosis.citations import check_cited_domains
from app.pipeline.diagnosis.config import get_diagnosis_config
from app.pipeline.diagnosis.contracts import (
    BotAudit,
    DiagnosisContext,
    Evidence,
    Finding,
    Gap,
)
from app.pipeline.diagnosis.fetcher import Fetcher, FetchResult
from app.pipeline.diagnosis.geo import (
    assess_geo_content,
    check_owned_comparison_page,
    check_third_party_presence,
)
from app.pipeline.diagnosis.llms_txt import check_llms_txt
from app.pipeline.diagnosis.probe import downgrade_truncated_absences, probe
from app.pipeline.diagnosis.robots_audit import audit_robots
from app.pipeline.diagnosis.seo import check_seo
from app.pipeline.diagnosis.sitemap import SitemapInventory, fetch_sitemap
from app.pipeline.diagnosis.taxonomy import findings_to_gaps


class DiagState(TypedDict, total=False):
    context: DiagnosisContext
    home: FetchResult
    home_evidence: list[Evidence]
    home_ok: bool
    findings: list[Finding]
    bot_audit: BotAudit
    gaps: list[Gap]


def build_diagnosis_graph(fetcher: Fetcher, gateway: Gateway):
    max_pages = get_diagnosis_config().scraper.max_pages_per_scan

    def fetch_home(state: DiagState) -> DiagState:
        p = probe(fetcher, state["context"].target_url)
        home = p.result or FetchResult(
            url=p.url, final_url=p.url, status=p.evidence.status or 0, ok=False
        )
        return {"home": home, "home_evidence": [p.evidence], "home_ok": p.present}

    def run_checks(state: DiagState) -> DiagState:
        context = state["context"]
        home = state["home"]
        home_ev = state.get("home_evidence", [])
        findings: list[Finding] = []

        bot_audit, robot_findings, robots_text = audit_robots(
            fetcher, context.target_url
        )
        findings.extend(robot_findings)
        findings.append(check_llms_txt(fetcher, context.target_url))

        # If the homepage never loaded, every page-level check would be reading an
        # empty document and would report missing schema / no H1 / no comparison
        # page — three confident findings from one failed fetch. Report the
        # failure once instead.
        if not state.get("home_ok", False):
            findings.append(
                Finding(
                    layer="seo",
                    code="page_fetch_failed",
                    ok=True,  # never a gap
                    severity="info",
                    summary=(
                        f"Could not fetch {context.target_url} — page-level checks "
                        "were skipped rather than reported as failures."
                    ),
                    status="check_failed",
                    confidence=0.0,
                    evidence=home_ev,
                )
            )
            # The citation checks read the scan's OWN citation list, not the
            # customer's site, so a failed homepage fetch tells us nothing about
            # them. Skipping them here threw away the one part of diagnosis that
            # still had evidence to work with.
            cited = check_cited_domains(context)
            if cited is not None:
                findings.append(cited)
            return {
                "findings": downgrade_truncated_absences(findings),
                "bot_audit": bot_audit,
            }

        sitemap: SitemapInventory = fetch_sitemap(
            fetcher, context.target_url, robots_text, max_children=max_pages
        )
        findings.extend(check_seo(home, home_ev))
        findings.append(check_owned_comparison_page(home, sitemap))
        # Domain-level citation questions first: no HTTP, so this one cannot
        # false-positive on a URL it failed to fetch.
        cited = check_cited_domains(context)
        if cited is not None:
            findings.append(cited)
        third_party = check_third_party_presence(fetcher, context, max_pages)
        if third_party is not None:
            findings.append(third_party)
        findings.extend(assess_geo_content(gateway, context, home, home_ev))

        # Applied to EVERY finding, once, at the end: an absence concluded from a
        # page we only partly read is a check that didn't finish, not a gap. Doing
        # it here rather than in each check means a check added later cannot forget.
        return {
            "findings": downgrade_truncated_absences(findings),
            "bot_audit": bot_audit,
        }

    def map_gaps(state: DiagState) -> DiagState:
        return {"gaps": findings_to_gaps(state["findings"])}

    graph = StateGraph(DiagState)
    graph.add_node("fetch_home", fetch_home)
    graph.add_node("run_checks", run_checks)
    graph.add_node("map_gaps", map_gaps)
    graph.add_edge(START, "fetch_home")
    graph.add_edge("fetch_home", "run_checks")
    graph.add_edge("run_checks", "map_gaps")
    graph.add_edge("map_gaps", END)
    return graph.compile()
