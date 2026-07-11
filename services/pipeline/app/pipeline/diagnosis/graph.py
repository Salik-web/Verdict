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
from app.pipeline.diagnosis.config import get_diagnosis_config
from app.pipeline.diagnosis.contracts import (
    BotAudit,
    DiagnosisContext,
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
from app.pipeline.diagnosis.robots_audit import audit_robots
from app.pipeline.diagnosis.seo import check_seo
from app.pipeline.diagnosis.taxonomy import findings_to_gaps


class DiagState(TypedDict, total=False):
    context: DiagnosisContext
    home: FetchResult
    findings: list[Finding]
    bot_audit: BotAudit
    gaps: list[Gap]


def build_diagnosis_graph(fetcher: Fetcher, gateway: Gateway):
    max_pages = get_diagnosis_config().scraper.max_pages_per_scan

    def fetch_home(state: DiagState) -> DiagState:
        return {"home": fetcher.get(state["context"].target_url)}

    def run_checks(state: DiagState) -> DiagState:
        context = state["context"]
        home = state["home"]
        findings: list[Finding] = []

        bot_audit, robot_findings = audit_robots(fetcher, context.target_url)
        findings.extend(robot_findings)
        findings.append(check_llms_txt(fetcher, context.target_url))
        findings.extend(check_seo(home))
        findings.append(check_owned_comparison_page(home))
        third_party = check_third_party_presence(fetcher, context, max_pages)
        if third_party is not None:
            findings.append(third_party)
        findings.extend(assess_geo_content(gateway, context, home))

        return {"findings": findings, "bot_audit": bot_audit}

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
