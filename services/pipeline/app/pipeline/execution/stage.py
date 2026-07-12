"""Execution stage: plan the gaps, then generate + validate the ONE top fix.

Pure w.r.t. the DB; the runner loads context/gaps and persists the asset. Runs in
mock mode with no API keys.
"""

from __future__ import annotations

from app.gateway import Gateway, get_gateway
from app.pipeline.execution.base import Generator
from app.pipeline.execution.contracts import (
    ExecutionOutput,
    GapInput,
    GeneratorContext,
)
from app.pipeline.execution.planner import plan
from app.pipeline.execution.registry import build_registry
from app.pipeline.execution.validate import finalize_asset


def generate_top_fix(
    gaps: list[GapInput],
    context: GeneratorContext,
    gateway: Gateway | None = None,
    registry: dict[str, Generator] | None = None,
) -> ExecutionOutput:
    backlog = plan(gaps)
    if not backlog.items:
        raise ValueError("no gaps to plan")
    top = backlog.items[0]

    registry = registry or build_registry(gateway or get_gateway())
    generator = registry.get(top.fix_type)
    if generator is None:
        raise ValueError(f"no generator registered for fix_type '{top.fix_type}'")

    target_ids = top.target_prompt_ids or context.target_prompt_ids
    ctx = context.model_copy(update={"target_prompt_ids": target_ids})

    draft = generator.generate(top, ctx)
    asset = finalize_asset(draft, ctx)
    return ExecutionOutput(backlog=backlog, plan_item=top, asset=asset)


class ExecutionStage:
    def __init__(
        self,
        gateway: Gateway | None = None,
        registry: dict[str, Generator] | None = None,
    ) -> None:
        self._gateway = gateway
        self._registry = registry

    def run(self, gaps: list[GapInput], context: GeneratorContext) -> ExecutionOutput:
        return generate_top_fix(gaps, context, self._gateway, self._registry)
