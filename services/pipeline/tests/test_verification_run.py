"""Integration: ship an asset, verify it, get an honest before/after verdict.

Sets up an invisible "before" (0 self mentions over the demo account's prompts),
then runs verification — which re-runs those exact prompts through the mock
Monitor (Acme is mentioned there) — and expects an 'improved' verdict with
confidence, plus a persisted verifications row. Requires the migrated + seeded DB.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.db.base import SessionLocal
from app.db.models import Gap, Scan, Verification
from app.db.repositories import (
    AccountRepository,
    AssetRepository,
    MentionRepository,
    PromptRepository,
)
from app.gateway.cost import NullCostSink
from app.gateway.gateway import build_gateway
from app.gateway.models_config import get_models_config
from app.pipeline.contracts import MentionRecord
from app.pipeline.verification.runner import run_verification

DEMO_ACCOUNT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _db_ready() -> bool:
    try:
        with SessionLocal() as s:
            s.connection()
        return True
    except OperationalError:
        return False


def test_run_verification_reports_improvement():
    if not _db_ready():
        pytest.skip("database unreachable — run docker compose up + db:migrate/seed")

    with SessionLocal() as s:
        prompt_ids = [
            p.id
            for p in PromptRepository(s).list_by_account(
                DEMO_ACCOUNT_ID, active_only=True
            )
        ]
        assert prompt_ids, "seed must provide active prompts"

        # Give the demo account headroom so the quota double-check doesn't fire on
        # an accumulated dev DB (we're testing verification here, not quota).
        account = AccountRepository(s).get_by_id(DEMO_ACCOUNT_ID)
        original_plan = account.plan
        account.plan = "enterprise"

        # "Before": a completed scan where Acme was invisible on these prompts.
        before_scan = Scan(
            account_id=DEMO_ACCOUNT_ID, status="completed", engine_set=[]
        )
        s.add(before_scan)
        s.flush()
        MentionRepository(s).bulk_insert(
            DEMO_ACCOUNT_ID,
            before_scan.id,
            [
                MentionRecord(
                    prompt_id=pid,
                    engine="chatgpt",
                    run=run,
                    brand="Acme Analytics",
                    competitor_id=None,
                    mentioned=False,
                    position=None,
                    sentiment=None,
                    sentiment_score=None,
                    cited_urls=[],
                )
                for pid in prompt_ids
                for run in range(1, 6)
            ],
        )

        # A gap tied to that scan, and the shipped asset that fixes it.
        gap = Gap(
            account_id=DEMO_ACCOUNT_ID,
            scan_id=before_scan.id,
            gap_type="no_owned_comparison_page",
            status="resolved",
            details={"fix_type": "generate_comparison_page"},
        )
        s.add(gap)
        s.flush()
        asset_id = uuid.uuid4()
        AssetRepository(s).create(
            account_id=DEMO_ACCOUNT_ID,
            asset_id=asset_id,
            gap_id=gap.id,
            type="comparison_page",
            title="Acme vs Globex",
            content_ref="artifacts/demo/x.html",
            metadata={},
            target_prompt_ids=prompt_ids,
            status="validated",
            validation_state="passed",
        )
        s.commit()

    try:
        gw = build_gateway(
            mode="mock", cost_sink=NullCostSink(), config=get_models_config()
        )
        result = run_verification(DEMO_ACCOUNT_ID, asset_id, gateway=gw)

        # Invisible before, mentioned after -> honest 'improved' with confidence.
        assert result["before"]["mention_rate"] == 0.0
        assert result["after"]["mention_rate"] > result["before"]["mention_rate"]
        assert result["verdict"] == "improved"
        assert result["delta"] > 0
        assert 0.0 < result["confidence"] <= 1.0

        # Persisted, tenant-scoped, linked to both scans.
        with SessionLocal() as s:
            row = s.scalars(
                select(Verification).where(Verification.asset_id == asset_id)
            ).first()
            after_scan = s.get(Scan, uuid.UUID(result["scan_after_id"]))
        assert row is not None
        assert row.verdict == "improved"
        assert str(row.scan_before_id) == result["scan_before_id"]
        assert after_scan.triggered_by == "verification"
    finally:
        with SessionLocal() as s:
            AccountRepository(s).get_by_id(DEMO_ACCOUNT_ID).plan = original_plan
            s.commit()
