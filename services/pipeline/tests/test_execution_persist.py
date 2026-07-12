"""Integration: run_execution for the demo account persists a validated,
downloadable, prompt-tagged comparison-page asset. Requires the migrated + seeded
DB (seed includes the demo account's verified_facts). Skips if unreachable."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.exc import OperationalError

from app.db.base import SessionLocal
from app.db.models import Gap as GapRow
from app.db.models import Scan
from app.db.repositories import AssetRepository
from app.gateway.cost import NullCostSink
from app.gateway.gateway import build_gateway
from app.gateway.models_config import get_models_config
from app.pipeline.execution.config import PIPELINE_ROOT
from app.pipeline.execution.runner import run_execution

DEMO_ACCOUNT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _db_ready() -> bool:
    try:
        with SessionLocal() as s:
            s.connection()
        return True
    except OperationalError:
        return False


def test_run_execution_persists_tagged_asset():
    if not _db_ready():
        pytest.skip("database unreachable — run docker compose up + db:migrate/seed")

    # Scope to a fresh scan so leftover gaps from other tests don't interfere.
    with SessionLocal() as s:
        scan = Scan(account_id=DEMO_ACCOUNT_ID, status="completed", engine_set=[])
        s.add(scan)
        s.flush()
        scan_id = scan.id
        s.add(
            GapRow(
                account_id=DEMO_ACCOUNT_ID,
                scan_id=scan_id,
                gap_type="no_owned_comparison_page",
                rank_score=Decimal("0.9"),
                status="open",
                details={"fix_type": "generate_comparison_page"},
            )
        )
        s.commit()

    gw = build_gateway(
        mode="mock", cost_sink=NullCostSink(), config=get_models_config()
    )
    result = run_execution(DEMO_ACCOUNT_ID, scan_id=scan_id, gateway=gw)

    assert result["type"] == "comparison_page"
    assert result["status"] == "validated"
    assert result["validation_state"] == "passed"
    assert result["target_prompt_ids"], "asset must be tagged to its queries"

    # Downloadable artifact file exists.
    assert (PIPELINE_ROOT / result["content_ref"]).exists()

    # Persisted, tenant-scoped, tagged.
    with SessionLocal() as s:
        row = AssetRepository(s).get(DEMO_ACCOUNT_ID, result["asset_id"])
    assert row is not None
    assert row.status == "validated"
    assert len(row.target_prompt_ids) == len(result["target_prompt_ids"])
    assert "<script" not in (PIPELINE_ROOT / result["content_ref"]).read_text().lower()
