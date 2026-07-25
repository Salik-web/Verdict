"""Mock provider — returns canned fixture responses, no network, no API key.

This is the DEFAULT, so the whole pipeline runs end-to-end with zero keys.
Fixtures live in config/fixtures/<fixture_dir>/<scenario>.json and are
scenario-able: pass scenario="competitor_wins" (etc.) in params, or fall back to
the task's default_scenario.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.gateway.models_config import FIXTURES_DIR, ResolvedTarget
from app.gateway.providers.base import Provider
from app.gateway.providers.registry import register_provider
from app.gateway.types import Message, ProviderResult, Usage


@register_provider("mock")
class MockProvider(Provider):
    def __init__(self, fixtures_dir: Path = FIXTURES_DIR) -> None:
        self.fixtures_dir = fixtures_dir

    def generate(
        self,
        target: ResolvedTarget,
        messages: list[Message],
        params: dict[str, Any],
    ) -> ProviderResult:
        if not target.fixture_dir:
            raise ValueError(
                f"mock target for task '{target.task}' has no fixture_dir configured"
            )
        scenario = params.get("scenario") or target.default_scenario
        if not scenario:
            raise ValueError(
                f"no scenario given and no default_scenario for task '{target.task}'"
            )

        path = self.fixtures_dir / target.fixture_dir / f"{scenario}.json"
        if not path.exists():
            available = sorted(p.stem for p in path.parent.glob("*.json"))
            raise FileNotFoundError(
                f"fixture '{scenario}' not found in {path.parent} (have: {available})"
            )

        fixture = json.loads(path.read_text(encoding="utf-8"))
        raw_text = fixture["text"]
        text = raw_text if isinstance(raw_text, str) else json.dumps(raw_text)
        usage = Usage.model_validate(fixture.get("usage", {}))
        return ProviderResult(text=text, usage=usage, raw=fixture)
