"""Integration: trigger a scan for the demo account (mock mode) and verify that
mentions rows + a share_of_voice row appear with correct SoV math.

Requires the migrated + seeded local DB; skips cleanly if unreachable.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import OperationalError

from app.db.base import SessionLocal
from app.db.models import Scan
from app.db.repositories import (
    MentionRepository,
    ScanRepository,
    ShareOfVoiceRepository,
)
from app.pipeline.monitor.runner import run_scan

DEMO_ACCOUNT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _db_ready() -> bool:
    try:
        with SessionLocal() as s:
            s.connection()
        return True
    except OperationalError:
        return False


@pytest.fixture
def demo_scan_id():
    if not _db_ready():
        pytest.skip("database unreachable — run docker compose up + db:migrate/seed")
    with SessionLocal() as s:
        scan = Scan(account_id=DEMO_ACCOUNT_ID, status="pending", engine_set=[])
        s.add(scan)
        s.commit()
        return scan.id


def test_run_scan_persists_mentions_and_sov(demo_scan_id):
    stats = run_scan(DEMO_ACCOUNT_ID, demo_scan_id)

    # Demo account has 3 active prompts x 1 engine x 5 repeats = 15 mentions.
    assert stats["mentions"] == 15

    with SessionLocal() as s:
        assert (
            ScanRepository(s).get(DEMO_ACCOUNT_ID, demo_scan_id).status == "completed"
        )
        assert MentionRepository(s).count_for_scan(DEMO_ACCOUNT_ID, demo_scan_id) == 15

        sov = ShareOfVoiceRepository(s).list_for_scan(DEMO_ACCOUNT_ID, demo_scan_id)
        allrows = {r.brand: r for r in sov if r.engine == "all"}

    # Acme mentioned in 3 of every 5 runs across 3 prompts -> 9 of 15.
    acme = allrows["Acme Analytics"]
    assert acme.mention_count == 9
    assert float(acme.mention_rate) == pytest.approx(0.6)
    assert acme.is_self is True
    assert float(acme.avg_position) == pytest.approx(4.0)

    # Total brand mentions = Acme9 + Globex15 + Initech15 + Mixpanel9 + Amplitude6 = 54.
    assert float(acme.sov_pct) == pytest.approx(9 / 54 * 100, abs=1e-3)
    assert sum(float(r.sov_pct) for r in allrows.values()) == pytest.approx(
        100.0, abs=1e-3
    )
