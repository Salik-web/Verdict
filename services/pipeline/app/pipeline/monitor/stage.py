"""Monitor stage entry point.

`run_monitor(context, gateway)` runs the LangGraph and returns a typed
MonitorOutput. Pure and DB-free: the runner loads the ScanContext and persists
the output. In mock mode this executes end-to-end with no API keys.
"""

from __future__ import annotations

from app.gateway import Gateway, get_gateway
from app.pipeline.contracts import MonitorOutput, ScanContext
from app.pipeline.monitor.config import get_monitor_config
from app.pipeline.monitor.graph import build_monitor_graph


def run_monitor(context: ScanContext, gateway: Gateway | None = None) -> MonitorOutput:
    gateway = gateway or get_gateway()
    cfg = get_monitor_config()
    wanted = set(context.engines)
    engines = [e for e in cfg.engines if e.name in wanted]
    if not engines:
        raise ValueError(f"no configured engines match {sorted(wanted)}")

    graph = build_monitor_graph(gateway, engines)
    final = graph.invoke({"context": context})
    return MonitorOutput(
        scan_id=context.scan_id,
        mentions=final["mentions"],
        share_of_voice=final["share_of_voice"],
    )


class MonitorStage:
    """Object form of the stage, for symmetry with later stages / DI in tests."""

    def __init__(self, gateway: Gateway | None = None) -> None:
        self._gateway = gateway

    def run(self, context: ScanContext) -> MonitorOutput:
        return run_monitor(context, self._gateway)
