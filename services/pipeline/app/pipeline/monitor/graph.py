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


def build_monitor_graph(gateway: Gateway, engines: list[EngineConfig]):
    def measure_and_parse(state: MonitorState) -> MonitorState:
        context = state["context"]
        resolve = make_brand_resolver(context)
        focal_competitor_id, _ = resolve(context.brand_name)

        parses: list[EngineParse] = []
        mentions: list[MentionRecord] = []

        for engine in engines:
            for prompt in context.prompts:
                for run in range(1, context.repeats + 1):
                    scenario = engine.scenario_for_run(run - 1)
                    answer = measure_once(
                        gateway,
                        account_id=context.account_id,
                        scan_id=context.scan_id,
                        prompt=prompt,
                        gateway_task=engine.gateway_task,
                        scenario=scenario,
                    )
                    parsed = parse_answer(
                        gateway, context, answer_text=answer.text, scenario=scenario
                    )
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
        return {"parses": parses, "mentions": mentions}

    def compute_share_of_voice(state: MonitorState) -> MonitorState:
        return {"share_of_voice": compute_sov(state["context"], state["parses"])}

    graph = StateGraph(MonitorState)
    graph.add_node("measure_and_parse", measure_and_parse)
    graph.add_node("compute_share_of_voice", compute_share_of_voice)
    graph.add_edge(START, "measure_and_parse")
    graph.add_edge("measure_and_parse", "compute_share_of_voice")
    graph.add_edge("compute_share_of_voice", END)
    return graph.compile()
