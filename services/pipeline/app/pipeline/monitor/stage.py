# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Monitor stage entry point.

`run_monitor(context, gateway)` runs the LangGraph and returns a typed
MonitorOutput. Pure and DB-free: the runner loads the ScanContext and persists
the output. In mock mode this executes end-to-end with no API keys.

Engines whose provider key is not configured are dropped BEFORE any call is
made, so a user who supplied only one engine's key gets a working single-engine
scan rather than a scan that dies partway through having already spent money on
the engines that did work. Only an empty result after filtering is an error, and
it names the env vars to set.
"""

from __future__ import annotations

import logging

from app.gateway import Gateway, get_gateway
from app.gateway.availability import task_status
from app.pipeline.contracts import MonitorOutput, ScanContext
from app.pipeline.monitor.config import EngineConfig, get_monitor_config
from app.pipeline.monitor.graph import build_monitor_graph

log = logging.getLogger(__name__)


class NoEngineAvailable(RuntimeError):
    """No requested engine has a usable API key in this deployment."""


def available_engines(
    engines: list[EngineConfig], gateway: Gateway
) -> tuple[list[EngineConfig], list[str]]:
    """Split configured engines into (usable, reasons-they-are-not)."""
    usable: list[EngineConfig] = []
    unavailable: list[str] = []
    for engine in engines:
        status = task_status(engine.gateway_task, gateway.mode, gateway.config)
        if status.available:
            usable.append(engine)
        else:
            unavailable.append(f"{engine.name} ({status.reason})")
    return usable, unavailable


def run_monitor(context: ScanContext, gateway: Gateway | None = None) -> MonitorOutput:
    gateway = gateway or get_gateway()
    cfg = get_monitor_config()
    wanted = set(context.engines)
    engines = [e for e in cfg.engines if e.name in wanted]
    if not engines:
        raise ValueError(f"no configured engines match {sorted(wanted)}")

    engines, unavailable = available_engines(engines, gateway)
    if unavailable:
        # Not an error while at least one engine works — a partial scan of the
        # engines the user actually pays for is the point of BYOK.
        log.warning("skipping unavailable engine(s): %s", "; ".join(unavailable))
    if not engines:
        raise NoEngineAvailable(
            "No measurement engine is available in this deployment. "
            + "; ".join(unavailable)
        )

    graph = build_monitor_graph(gateway, engines)
    final = graph.invoke({"context": context})
    return MonitorOutput(
        scan_id=context.scan_id,
        mentions=final["mentions"],
        share_of_voice=final["share_of_voice"],
        failed_observations=final.get("failed_observations", []),
    )


class MonitorStage:
    """Object form of the stage, for symmetry with later stages / DI in tests."""

    def __init__(self, gateway: Gateway | None = None) -> None:
        self._gateway = gateway

    def run(self, context: ScanContext) -> MonitorOutput:
        return run_monitor(context, self._gateway)
