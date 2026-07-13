"""Scheduler math (pure): deterministic per-account jitter + due decisions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.pipeline.schedule.config import ScheduleConfig
from app.pipeline.schedule.jitter import (
    is_due,
    jitter_offset_seconds,
    next_run_at,
)

CFG = ScheduleConfig(cadence_days=7, jitter_minutes=720, tick_minutes=15)


def test_offset_is_deterministic_and_bounded():
    aid = uuid.uuid4()
    window = CFG.jitter_minutes * 60
    a = jitter_offset_seconds(aid, window)
    b = jitter_offset_seconds(aid, window)
    assert a == b  # stable across calls — no random state to persist
    assert 0 <= a < window


def test_cohort_spreads_out():
    # Distinct accounts land in distinct slots -> no thundering herd.
    window = CFG.jitter_minutes * 60
    offsets = {jitter_offset_seconds(uuid.uuid4(), window) for _ in range(200)}
    assert len(offsets) > 150  # overwhelmingly unique across the window


def test_due_after_a_full_cadence():
    aid = uuid.uuid4()
    now = datetime(2026, 7, 13, tzinfo=UTC)
    fresh = now - timedelta(days=1)  # scanned yesterday
    stale = now - timedelta(days=30)  # long overdue

    assert is_due(aid, fresh, now, CFG) is False
    assert is_due(aid, stale, now, CFG) is True

    # An account scanned exactly a cadence ago is due only after its jitter slot.
    boundary = now - timedelta(days=CFG.cadence_days)
    expected = next_run_at(aid, boundary, now, CFG)
    assert is_due(aid, boundary, expected, CFG) is True
    assert is_due(aid, boundary, expected - timedelta(seconds=1), CFG) is False
