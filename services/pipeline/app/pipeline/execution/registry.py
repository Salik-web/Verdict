"""Generator registry: fix_type -> Generator. New fix types register here."""

from __future__ import annotations

from app.gateway import Gateway
from app.pipeline.execution.base import Generator
from app.pipeline.execution.generators import (
    ComparisonPageGenerator,
    LlmsTxtGenerator,
    RobotsTxtFixer,
)


def build_registry(gateway: Gateway) -> dict[str, Generator]:
    generators: list[Generator] = [
        ComparisonPageGenerator(gateway),
        RobotsTxtFixer(),
        LlmsTxtGenerator(),
    ]
    return {g.fix_type: g for g in generators}
