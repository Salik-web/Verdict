# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""The Monitor stage as a LangGraph.

  measure_and_parse --> compute_share_of_voice

`measure_and_parse` asks each engine each active prompt `repeats` times and runs
the LLM-as-judge parser on every answer, emitting one focal-brand MentionRecord
per (prompt, engine, run). `compute_share_of_voice` aggregates the parses.

The graph is pure w.r.t. the DB: it takes a ScanContext and returns records; the
runner persists them. In mock mode it needs no network and no API keys.
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.gateway import Gateway
from app.pipeline.contracts import (
    CitationSource,
    FailedObservation,
    MentionRecord,
    ScanContext,
    SoVRecord,
)
from app.pipeline.monitor.config import EngineConfig
from app.pipeline.monitor.measure import measure_once
from app.pipeline.monitor.parse import parse_answer
from app.pipeline.monitor.records import records_for_answer
from app.pipeline.monitor.sov import EngineParse, compute_sov, make_brand_resolver


class MonitorState(TypedDict, total=False):
    context: ScanContext
    parses: list[EngineParse]
    mentions: list[MentionRecord]
    share_of_voice: list[SoVRecord]
    failed_observations: list[FailedObservation]


def build_monitor_graph(gateway: Gateway, engines: list[EngineConfig]):
    def measure_and_parse(state: MonitorState) -> MonitorState:
        context = state["context"]
        resolve = make_brand_resolver(context)
        focal_competitor_id, _ = resolve(context.brand_name)

        parses: list[EngineParse] = []
        mentions: list[MentionRecord] = []
        failures: list[FailedObservation] = []

        for engine in engines:
            for prompt in context.prompts:
                for run in range(1, context.repeats + 1):
                    scenario = engine.scenario_for_run(run - 1, gateway.mode)
                    try:
                        answer = measure_once(
                            gateway,
                            account_id=context.account_id,
                            scan_id=context.scan_id,
                            prompt=prompt,
                            gateway_task=engine.gateway_task,
                            scenario=scenario,
                        )
                    except Exception as exc:
                        # An answer we never received is not an answer in which the
                        # brand was absent. Drop the observation instead of storing
                        # a confident mentioned=False — and keep scanning, because
                        # one refused call must not void the other nine.
                        failures.append(
                            FailedObservation(
                                prompt_id=prompt.id,
                                engine=engine.name,
                                run=run,
                                stage="measurement",
                                reason=f"{type(exc).__name__}: {exc}"[:500],
                                finish_reason=getattr(exc, "finish_reason", None),
                            )
                        )
                        continue

                    # Same rule for a cut-off answer: it is evidence of what WAS
                    # said, never evidence of what was not said, so it cannot
                    # support a mentioned=False observation either.
                    if answer.truncated:
                        failures.append(
                            FailedObservation(
                                prompt_id=prompt.id,
                                engine=f"{answer.provider}/{answer.model}",
                                run=run,
                                stage="measurement",
                                reason="answer truncated before completion",
                                finish_reason=answer.finish_reason,
                            )
                        )
                        continue

                    try:
                        parsed = parse_answer(
                            gateway, context, answer_text=answer.text, scenario=scenario
                        )
                    except Exception as exc:
                        # We have the answer but no reliable reading of it. Counting
                        # it would be inventing a result; excluding it is honest.
                        failures.append(
                            FailedObservation(
                                prompt_id=prompt.id,
                                engine=f"{answer.provider}/{answer.model}",
                                run=run,
                                stage="parse",
                                reason=f"{type(exc).__name__}: {exc}"[:500],
                            )
                        )
                        continue
                    # #1 The engine label is the model that ACTUALLY answered, not
                    # the config slot name — so the DB never misattributes (the
                    # "perplexity_sonar" slot resolving to Gemini in dev is the bug
                    # this fixes). Same label for every row of this answer + SoV.
                    engine_label = f"{answer.provider}/{answer.model}"

                    # #3 Prefer the engine's own grounded sources (url + publisher
                    # title); fall back to the LLM-judge's inferred URLs (no title).
                    if answer.sources:
                        cited = [
                            CitationSource(url=s.url, title=s.title)
                            for s in answer.sources
                        ]
                    else:
                        cited = [CitationSource(url=u) for u in parsed.cited_urls]

                    parses.append((engine_label, parsed))
                    # One target row (carrying the per-answer raw text + citations)
                    # plus one row per named competitor — see records_for_answer,
                    # shared with the re-parse path so they can't drift.
                    mentions.extend(
                        records_for_answer(
                            prompt_id=prompt.id,
                            engine=engine_label,
                            run=run,
                            brand_name=context.brand_name,
                            focal_competitor_id=focal_competitor_id,
                            parsed=parsed,
                            cited=cited,
                            raw_response=answer.text,
                            resolve=resolve,
                        )
                    )
        # `observations` downstream is len(parses) — so a failed observation is
        # excluded from every rate's denominator simply by never being appended.
        return {
            "parses": parses,
            "mentions": mentions,
            "failed_observations": failures,
        }

    def compute_share_of_voice(state: MonitorState) -> MonitorState:
        return {"share_of_voice": compute_sov(state["context"], state["parses"])}

    graph = StateGraph(MonitorState)
    graph.add_node("measure_and_parse", measure_and_parse)
    graph.add_node("compute_share_of_voice", compute_share_of_voice)
    graph.add_edge(START, "measure_and_parse")
    graph.add_edge("measure_and_parse", "compute_share_of_voice")
    graph.add_edge("compute_share_of_voice", END)
    return graph.compile()
