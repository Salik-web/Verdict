# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Diagnosis stage entry point.

`diagnose(context, fetcher, gateway)` runs the LangGraph and returns a typed
DiagnosisOutput. Pure w.r.t. the DB; the runner loads the context and persists
Gaps. The default fetcher is config-driven (see `default_fetcher`); the gateway
defaults to mock mode.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.gateway import Gateway, get_gateway
from app.pipeline.diagnosis.config import get_diagnosis_config
from app.pipeline.diagnosis.contracts import DiagnosisContext, DiagnosisOutput
from app.pipeline.diagnosis.fetcher import Fetcher, FixtureFetcher, HttpxFetcher
from app.pipeline.diagnosis.graph import build_diagnosis_graph


def default_fetcher() -> Fetcher:
    """Pick the fetcher from config (never inline): `fixture` serves the canned
    site offline, `http` hits the real network, `auto` uses fixtures whenever the
    gateway is in mock mode — so the whole pipeline stays runnable with no keys,
    no network, and no dependence on the account's domain resolving."""
    cfg = get_diagnosis_config()
    mode = cfg.fetcher.mode
    if mode == "auto":
        mode = "fixture" if get_settings().gateway_mode == "mock" else "http"
    if mode == "fixture":
        return FixtureFetcher(cfg.fetcher.fixtures_path())
    return HttpxFetcher(cfg.scraper)


def diagnose(
    context: DiagnosisContext,
    fetcher: Fetcher | None = None,
    gateway: Gateway | None = None,
) -> DiagnosisOutput:
    fetcher = fetcher or default_fetcher()
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
