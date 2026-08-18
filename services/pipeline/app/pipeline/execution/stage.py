# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Execution stage: plan the gaps, then generate + validate the top fix IF a
generator exists for it.

Pure w.r.t. the DB; the runner loads context/gaps and persists any asset.

Two outcomes are ordinary, not failures, and both still carry the backlog:

  * **Nothing to plan.** No rankable gaps — a clean site, or every gap below the
    planner's detection-confidence floor.
  * **No generator for any ranked fix_type.** Some fixes are inherently advisory
    (`remove_noindex` is fixed by deleting a meta tag, not by us shipping a
    file), and this distribution registers no generators at all, so this is the
    normal path here. The backlog is the useful output either way; execution
    reports which fix_types it could not build and moves on.

Only `GenerationBlocked` still raises, and it means something different: a
generator WAS available and we deliberately refused to publish something hollow
(no verified facts, unfilled placeholders). That refusal is a product decision
worth surfacing loudly, so it stays an exception — the runner records it with
the backlog attached.
"""

from __future__ import annotations

from app.gateway import Gateway
from app.pipeline.execution.base import Generator
from app.pipeline.execution.contracts import (
    ExecutionOutput,
    GapInput,
    GeneratorContext,
)
from app.pipeline.execution.facts_gate import GenerationBlocked, sanitize_context
from app.pipeline.execution.planner import plan
from app.pipeline.execution.registry import build_registry
from app.pipeline.execution.validate import finalize_asset


def generate_top_fix(
    gaps: list[GapInput],
    context: GeneratorContext,
    gateway: Gateway | None = None,
    registry: dict[str, Generator] | None = None,
    confidence_overrides: dict[str, float] | None = None,
) -> ExecutionOutput:
    backlog = plan(gaps, confidence_overrides)
    if not backlog.items:
        return ExecutionOutput(
            backlog=backlog,
            reason=(
                "No rankable gaps — nothing to plan. (Gaps below the planner's "
                "detection-confidence floor are still recorded for the report.)"
            ),
        )

    # `registry is None` means "discover"; an explicitly passed {} means "this
    # process has no generators", and both legitimately end up empty.
    registry = build_registry(gateway) if registry is None else registry

    # Ship the highest-ranked fix WE CAN BUILD. Everything ranked above it that
    # has no generator is advisory: recorded, reported, not built.
    unsupported: list[str] = []
    top = None
    for item in backlog.items:
        if item.fix_type in registry:
            top = item
            break
        unsupported.append(item.fix_type)

    if top is None:
        return ExecutionOutput(
            backlog=backlog,
            unsupported_fix_types=unsupported,
            reason=(
                "No generator available for this fix_type: "
                + ", ".join(unsupported)
                + ". The ranked backlog is still available; register a generator "
                "(entry point 'geo.generators') to build these automatically."
            ),
        )

    generator = registry[top.fix_type]

    target_ids = top.target_prompt_ids or context.target_prompt_ids
    # Shared pre-generation gate: strip unfilled placeholder facts for EVERY
    # generator. A generator can't publish "⚠️ your real starting price" if it
    # never receives it.
    ctx = sanitize_context(context.model_copy(update={"target_prompt_ids": target_ids}))

    try:
        draft = generator.generate(top, ctx)
        asset = finalize_asset(draft, ctx)
    except GenerationBlocked as blocked:
        # Carry the plan with the refusal — a caller that only sees "blocked"
        # loses the backlog, which is the part that is still actionable.
        blocked.detail.setdefault(
            "backlog", [(i.fix_type, i.score) for i in backlog.items]
        )
        blocked.detail.setdefault("fix_type", top.fix_type)
        raise

    return ExecutionOutput(
        backlog=backlog,
        plan_item=top,
        asset=asset,
        unsupported_fix_types=unsupported,
    )


class ExecutionStage:
    def __init__(
        self,
        gateway: Gateway | None = None,
        registry: dict[str, Generator] | None = None,
    ) -> None:
        self._gateway = gateway
        self._registry = registry

    def run(
        self,
        gaps: list[GapInput],
        context: GeneratorContext,
        confidence_overrides: dict[str, float] | None = None,
    ) -> ExecutionOutput:
        return generate_top_fix(
            gaps, context, self._gateway, self._registry, confidence_overrides
        )
