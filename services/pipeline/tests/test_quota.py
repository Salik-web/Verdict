"""Plan-quota config mapping (pure)."""

from __future__ import annotations

from app.pipeline.schedule.config import get_quota_config


def test_plan_caps_and_default():
    cfg = get_quota_config()
    assert cfg.monthly_scans("free") == 4
    assert cfg.monthly_scans("enterprise") == 1000
    # Unknown / missing plan falls back to the default cap.
    assert cfg.monthly_scans("mystery-plan") == cfg.default_monthly_scans
    assert cfg.monthly_scans(None) == cfg.default_monthly_scans
