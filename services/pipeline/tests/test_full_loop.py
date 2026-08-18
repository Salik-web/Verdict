# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""End-to-end hardening checkpoint: the whole loop on the demo account, in mock
mode, with the guards active.

  Monitor -> Diagnose -> Plan  (-> Execute, only if a generator is registered)

This distribution ships zero generators, so the loop ends at a ranked backlog.
That is the shape being pinned here: a full scan must COMPLETE and produce gaps
with nothing registered. Verification is covered in test_verification_run.py,
which supplies its own asset — the pipeline no longer produces one on its own.

Diagnosis runs offline through a FakeFetcher, but still against a *public* target
(8.8.8.8) so the SSRF guard is exercised (a private IP would be rejected). Every
model call goes through the gateway in mock mode and is logged to llm_cost_log,
which we then read back through the cost repository (all `mock`, zero real spend).
Requires the migrated + seeded DB; skips cleanly if unreachable.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import OperationalError

from app.db.base import SessionLocal
from app.db.models import Scan
from app.db.repositories import AccountRepository, LlmCostRepository
from app.gateway.gateway import build_gateway
from app.gateway.models_config import get_models_config
from app.pipeline.diagnosis.fetcher import FakeFetcher, FetchResult
from app.pipeline.diagnosis.runner import run_diagnosis
from app.pipeline.execution.runner import run_execution
from app.pipeline.monitor.runner import run_scan

DEMO_ACCOUNT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# Public IP so assert_public_url passes; FakeFetcher serves the bytes offline.
TARGET = "https://8.8.8.8/"
# Permissive robots -> no blocked_crawler gap, so the backlog is led by the
# content/structure fixes rather than a crawler unblock.
ROBOTS = "User-agent: *\nDisallow:"
HOME = "<html><body><h1>Acme Analytics</h1><p>Product analytics.</p></body></html>"
# A readable sitemap with no comparison URL: that is what makes "no owned
# comparison page" a CONFIRMED absence (whole inventory checked) instead of a
# low-confidence guess off the homepage, so the fix is allowed to be ranked.
SITEMAP = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    "<url><loc>https://8.8.8.8/</loc></url>"
    "<url><loc>https://8.8.8.8/pricing</loc></url>"
    "<url><loc>https://8.8.8.8/docs</loc></url>"
    "</urlset>"
)


def _db_ready() -> bool:
    try:
        with SessionLocal() as s:
            s.connection()
        return True
    except OperationalError:
        return False


def test_full_loop_on_demo_account():
    if not _db_ready():
        pytest.skip("database unreachable — run docker compose up + db:migrate/seed")

    # Mock gateway with the default DbCostSink so calls land in llm_cost_log.
    gw = build_gateway(mode="mock", config=get_models_config())

    with SessionLocal() as s:
        account = AccountRepository(s).get_by_id(DEMO_ACCOUNT_ID)
        original_plan = account.plan
        account.plan = "enterprise"  # headroom so the quota guard doesn't fire
        scan = Scan(account_id=DEMO_ACCOUNT_ID, status="pending", engine_set=[])
        s.add(scan)
        s.commit()
        scan_id = scan.id

    try:
        # 1. MONITOR — measure visibility.
        monitor = run_scan(DEMO_ACCOUNT_ID, scan_id, gw)
        assert monitor["mentions"] > 0

        # 2. DIAGNOSE — SSRF-guarded scrape (offline) -> typed gaps for this scan.
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
                f"{TARGET}sitemap.xml": FetchResult(
                    url=f"{TARGET}sitemap.xml",
                    final_url=f"{TARGET}sitemap.xml",
                    status=200,
                    ok=True,
                    text=SITEMAP,
                ),
            }
        )
        diagnosis = run_diagnosis(
            DEMO_ACCOUNT_ID,
            scan_id=scan_id,
            target_url=TARGET,
            fetcher=fetcher,
            gateway=gw,
        )
        assert diagnosis["gaps"] > 0
        assert not diagnosis["blocked_search_bots"]  # permissive robots

        # 3. PLAN — rank the gaps. This distribution registers NO generators, so
        # the backlog IS the deliverable: the run completes, reports which fix
        # types it cannot build, and never raises. (Registering a generator is
        # what turns this into a shipped asset — see test_no_generators.py.)
        execution = run_execution(DEMO_ACCOUNT_ID, scan_id=scan_id, gateway=gw)
        assert execution["skipped_generation"] is True
        assert "No generator available for this fix_type" in execution["reason"]
        assert execution["backlog"], "planning must still produce a ranked backlog"
        # Ranked, highest score first, and every item names a real fix_type.
        scores = [score for _, score in execution["backlog"]]
        assert scores == sorted(scores, reverse=True)
        assert all(fix_type for fix_type, _ in execution["backlog"])
        # Everything ranked is reported as unbuildable rather than silently lost.
        assert execution["unsupported_fix_types"] == [
            fix_type for fix_type, _ in execution["backlog"]
        ]
        # Nothing was written to disk, because nothing was generated.
        assert "asset_id" not in execution

        # Cost was logged for every mock call, and NOTHING was real spend.
        with SessionLocal() as s:
            costs = LlmCostRepository(s).summary(DEMO_ACCOUNT_ID)
        assert costs["calls"] > 0
        assert costs["real_calls"] == 0
        assert costs["mock_calls"] == costs["calls"]
    finally:
        with SessionLocal() as s:
            AccountRepository(s).get_by_id(DEMO_ACCOUNT_ID).plan = original_plan
            s.commit()
