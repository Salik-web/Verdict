# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Integration: run_diagnosis persists Gap rows for a scan (offline — fake
fetcher + mock gateway). Skips cleanly if the DB is unreachable."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import OperationalError

from app.db.base import SessionLocal
from app.db.models import Scan
from app.db.repositories import GapRepository
from app.gateway.cost import NullCostSink
from app.gateway.gateway import build_gateway
from app.gateway.models_config import get_models_config
from app.pipeline.diagnosis.fetcher import FakeFetcher, FetchResult
from app.pipeline.diagnosis.runner import run_diagnosis

DEMO_ACCOUNT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
TARGET = "https://8.8.8.8/"
ROBOTS = "User-agent: OAI-SearchBot\nDisallow: /\n\nUser-agent: *\nDisallow:"
HOME = "<html><body><h1>Acme</h1><p>Analytics.</p></body></html>"


def _db_ready() -> bool:
    try:
        with SessionLocal() as s:
            s.connection()
        return True
    except OperationalError:
        return False


def test_run_diagnosis_persists_gaps():
    if not _db_ready():
        pytest.skip("database unreachable — run docker compose up + db:migrate/seed")

    with SessionLocal() as s:
        scan = Scan(account_id=DEMO_ACCOUNT_ID, status="pending", engine_set=[])
        s.add(scan)
        s.commit()
        scan_id = scan.id

    fetcher = FakeFetcher(
        {
            TARGET: FetchResult(
                url=TARGET, final_url=TARGET, status=200, ok=True, text=HOME
            ),
            f"{TARGET}robots.txt": FetchResult(
                url=f"{TARGET}robots.txt",
                final_url=f"{TARGET}robots.txt",
                status=200,
                ok=True,
                text=ROBOTS,
            ),
        }
    )
    gateway = build_gateway(
        mode="mock", cost_sink=NullCostSink(), config=get_models_config()
    )

    result = run_diagnosis(
        DEMO_ACCOUNT_ID,
        scan_id=scan_id,
        target_url=TARGET,
        fetcher=fetcher,
        gateway=gateway,
    )
    assert result["gaps"] > 0
    assert "OAI-SearchBot" in result["blocked_search_bots"]

    with SessionLocal() as s:
        rows = GapRepository(s).list_for_scan(DEMO_ACCOUNT_ID, scan_id)
    assert len(rows) == result["gaps"]
    # fix_type is stored in details jsonb (no schema change).
    blocked = next(r for r in rows if r.gap_type == "blocked_crawler")
    assert blocked.details["fix_type"] == "fix_robots_txt"
    assert blocked.status == "open"
