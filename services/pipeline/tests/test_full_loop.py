"""End-to-end hardening checkpoint: the whole loop on the demo account, in mock
mode, with the guards active.

  Monitor -> Diagnose -> Plan+Execute -> Verify

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
from app.pipeline.execution.config import PIPELINE_ROOT
from app.pipeline.execution.runner import run_execution
from app.pipeline.monitor.runner import run_scan
from app.pipeline.verification.runner import run_verification

DEMO_ACCOUNT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# Public IP so assert_public_url passes; FakeFetcher serves the bytes offline.
TARGET = "https://8.8.8.8/"
# Permissive robots -> no blocked_crawler gap, so the top fix is the comparison
# page (which carries target_prompt_ids for verification).
ROBOTS = "User-agent: *\nDisallow:"
HOME = "<html><body><h1>Acme Analytics</h1><p>Product analytics.</p></body></html>"

VERDICTS = {"improved", "no_change", "regressed", "inconclusive"}


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

        # 3. PLAN + EXECUTE — ship the top fix from verified facts, sanitized.
        execution = run_execution(DEMO_ACCOUNT_ID, scan_id=scan_id, gateway=gw)
        assert execution["type"] == "comparison_page"
        assert execution["status"] == "validated"
        assert execution["target_prompt_ids"], "asset must be tagged to its queries"
        artifact = PIPELINE_ROOT / execution["content_ref"]
        assert artifact.exists()
        assert "<script" not in artifact.read_text(encoding="utf-8").lower()

        # 4. VERIFY — re-run those prompts, honest before/after verdict.
        verification = run_verification(
            DEMO_ACCOUNT_ID, execution["asset_id"], gateway=gw
        )
        assert verification["verdict"] in VERDICTS
        assert 0.0 <= verification["confidence"] <= 1.0

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
