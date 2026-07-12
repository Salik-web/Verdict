"""The common Generator interface.

`generate(item, context) -> AssetDraft`. New fix types drop in by implementing
this and registering the fix_type (see registry.py) — no changes to the stage.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.pipeline.execution.contracts import AssetDraft, GeneratorContext, PlanItem


class Generator(ABC):
    #: the fix_type this generator handles (matches the planner/taxonomy)
    fix_type: str
    #: the assets.type label recorded for produced assets
    asset_type: str

    @abstractmethod
    def generate(self, item: PlanItem, context: GeneratorContext) -> AssetDraft:
        """Produce a draft asset for a planned gap. Raises on unrecoverable error."""
