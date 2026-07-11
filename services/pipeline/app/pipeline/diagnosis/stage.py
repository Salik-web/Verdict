"""Diagnosis stage entry point.

`diagnose(context, fetcher, gateway)` runs the LangGraph and returns a typed
DiagnosisOutput. Pure w.r.t. the DB; the runner loads the context and persists
Gaps. Defaults: HttpxFetcher (real network, SSRF-guarded) + the mock-mode gateway.
"""

from __future__ import annotations

from app.gateway import Gateway, get_gateway
from app.pipeline.diagnosis.config import get_diagnosis_config
from app.pipeline.diagnosis.contracts import DiagnosisContext, DiagnosisOutput
from app.pipeline.diagnosis.fetcher import Fetcher, HttpxFetcher
from app.pipeline.diagnosis.graph import build_diagnosis_graph


def diagnose(
    context: DiagnosisContext,
    fetcher: Fetcher | None = None,
    gateway: Gateway | None = None,
) -> DiagnosisOutput:
    fetcher = fetcher or HttpxFetcher(get_diagnosis_config().scraper)
    gateway = gateway or get_gateway()

    graph = build_diagnosis_graph(fetcher, gateway)
    final = graph.invoke({"context": context})

    return DiagnosisOutput(
        target_url=context.target_url,
        findings=final["findings"],
        gaps=final["gaps"],
        bot_audit=final["bot_audit"],
    )


class DiagnosisStage:
    def __init__(
        self, fetcher: Fetcher | None = None, gateway: Gateway | None = None
    ) -> None:
        self._fetcher = fetcher
        self._gateway = gateway

    def run(self, context: DiagnosisContext) -> DiagnosisOutput:
        return diagnose(context, self._fetcher, self._gateway)
