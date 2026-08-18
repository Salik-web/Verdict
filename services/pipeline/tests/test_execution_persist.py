# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Integration: run_execution persists a validated, downloadable, prompt-tagged
asset for the demo account.

The PERSISTENCE path stays in this repo even though no generators do, because a
downstream product registers a generator and relies on exactly this behaviour:
artifact written to disk, assets row tenant-scoped and tagged with its target
prompts, HTML sanitized. So the test supplies its own generator, which is what a
downstream product does. Requires the migrated + seeded DB; skips if unreachable."""

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
from app.pipeline.execution.base import Generator
from app.pipeline.execution.config import PIPELINE_ROOT
from app.pipeline.execution.contracts import AssetDraft, GeneratorContext, PlanItem
from app.pipeline.execution.runner import run_execution

DEMO_ACCOUNT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# The script tag is deliberate: sanitization is part of what this test pins.
_PAGE = "<h1>Acme Analytics vs Globex</h1><script>alert(1)</script><p>Body.</p>"


class _ComparisonStub(Generator):
    fix_type = "generate_comparison_page"
    asset_type = "comparison_page"

    def generate(self, item: PlanItem, context: GeneratorContext) -> AssetDraft:
        return AssetDraft(
            asset_type=self.asset_type,
            fix_type=self.fix_type,
            title=f"{context.brand_name} vs Globex Insights",
            content=_PAGE,
            content_kind="html",
            target_prompt_ids=context.target_prompt_ids,
        )


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
    result = run_execution(
        DEMO_ACCOUNT_ID,
        scan_id=scan_id,
        gateway=gw,
        registry={"generate_comparison_page": _ComparisonStub()},
    )

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
