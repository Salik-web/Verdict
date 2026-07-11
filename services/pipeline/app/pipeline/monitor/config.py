"""Loaders for the monitor's data-driven config (config/monitor.yaml) and the
prompt templates (config/prompts/*.md). Nothing here is inline in logic."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

# services/pipeline/  (parents: [0]=monitor, [1]=pipeline, [2]=app, [3]=root)
_PIPELINE_ROOT = Path(__file__).resolve().parents[3]
MONITOR_CONFIG_PATH = _PIPELINE_ROOT / "config" / "monitor.yaml"
PROMPTS_DIR = _PIPELINE_ROOT / "config" / "prompts"


class EngineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    gateway_task: str = "measurement"
    mock_scenarios: list[str] = []

    def scenario_for_run(self, run_index: int) -> str | None:
        """Mock-only: cycle scenarios by run index so repeats vary."""
        if not self.mock_scenarios:
            return None
        return self.mock_scenarios[run_index % len(self.mock_scenarios)]


class MonitorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repeats: int = 5
    prompt_target_count: int = 28
    default_category: str = "B2B SaaS"
    engines: list[EngineConfig]


@lru_cache
def get_monitor_config() -> MonitorConfig:
    data = yaml.safe_load(MONITOR_CONFIG_PATH.read_text(encoding="utf-8"))
    return MonitorConfig.model_validate(data)


@lru_cache
def load_prompt_template(name: str) -> str:
    """Load a prompt template file (e.g. 'prompt_generation', 'mention_extraction')."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
