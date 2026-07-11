"""Opt-in live smoke test: real network fetch of example.com.

Skipped unless RUN_LIVE_SCRAPE=1 so the suite stays green offline/CI. The LLM
step still goes through the gateway in mock mode (no API keys).
"""

from __future__ import annotations

import os
import uuid

import pytest

from app.gateway.cost import NullCostSink
from app.gateway.gateway import build_gateway
from app.gateway.models_config import get_models_config
from app.pipeline.diagnosis.contracts import DiagnosisContext
from app.pipeline.diagnosis.stage import diagnose

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_SCRAPE") != "1",
    reason="set RUN_LIVE_SCRAPE=1 to run the live example.com scrape",
)


def test_live_diagnosis_example_com():
    context = DiagnosisContext(
        account_id=uuid.uuid4(),
        brand_name="Example",
        target_url="https://example.com/",
    )
    gateway = build_gateway(
        mode="mock", cost_sink=NullCostSink(), config=get_models_config()
    )
    out = diagnose(context, gateway=gateway)  # real HttpxFetcher

    assert out.findings
    assert out.bot_audit is not None
    # example.com has no structured data or llms.txt -> at least these gaps.
    gap_types = {g.gap_type for g in out.gaps}
    assert "missing_llms_txt" in gap_types
