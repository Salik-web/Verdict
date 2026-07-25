"""Runner: DB-facing orchestration for the Verification stage.

For a shipped asset it (1) reads the before-metric from the scan that surfaced the
gap, restricted to the asset's exact target prompts; (2) quota-checks, then runs a
fresh Monitor scan over those same prompts (reusing the Monitor stage wholesale);
(3) reads the after-metric the same way; (4) calls the pure `evaluate` to get an
honest verdict + confidence; (5) writes the verifications row. Runs end-to-end in
mock mode with no API keys.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.db.base import SessionLocal
from app.db.models import Gap
from app.db.repositories import (
    AccountRepository,
    AssetRepository,
    MentionRepository,
    ScanRepository,
    VerificationRepository,
)
from app.gateway import Gateway
from app.pipeline.monitor.runner import run_scan
from app.pipeline.quota import check_quota
from app.pipeline.verification.compare import evaluate
from app.pipeline.verification.contracts import SelfMetric, VerificationOutcome


def _self_metric(
    session,
    account_id: uuid.UUID,
    scan_id: uuid.UUID | None,
    prompt_ids: list,
    brand: str,
) -> SelfMetric:
    if scan_id is None:
        return SelfMetric()
    observations, mentioned, avg_position = MentionRepository(session).self_stats(
        account_id, scan_id, prompt_ids, brand
    )
    return SelfMetric(
        observations=observations,
        mentioned_count=mentioned,
        mention_rate=(round(mentioned / observations, 6) if observations else 0.0),
        avg_position=avg_position,
    )


def run_verification(
    account_id: uuid.UUID | str,
    asset_id: uuid.UUID | str,
    *,
    gateway: Gateway | None = None,
) -> dict[str, Any]:
    account_id = _as_uuid(account_id)
    asset_id = _as_uuid(asset_id)

    # 1. Resolve the asset, its target prompts, and the "before" scan (the scan
    #    that surfaced the gap this asset fixes). Quota-check before we spend.
    with SessionLocal() as session:
        asset = AssetRepository(session).get(account_id, asset_id)
        if asset is None:
            raise ValueError(f"asset {asset_id} not found for account {account_id}")
        target_prompt_ids = list(asset.target_prompt_ids or [])
        if not target_prompt_ids:
            raise ValueError(f"asset {asset_id} has no target prompts to verify")

        scan_before_id = None
        if asset.gap_id is not None:
            gap = session.get(Gap, asset.gap_id)
            scan_before_id = gap.scan_id if gap is not None else None

        # The brand whose visibility we measure — must match how the Monitor
        # labels the target row, so self_stats counts the right rows.
        account = AccountRepository(session).get_by_id(account_id)
        brand = (account.brand_name or account.name) if account else ""

        before = _self_metric(
            session, account_id, scan_before_id, target_prompt_ids, brand
        )
        check_quota(session, account_id, plan=account.plan if account else None)

        after_scan = ScanRepository(session).create(
            account_id, triggered_by="verification"
        )
        scan_after_id = after_scan.id
        session.commit()

    # 2. Re-run the Monitor stage over the asset's EXACT target prompts. This
    #    persists mentions + share_of_voice for the after scan.
    run_scan(account_id, scan_after_id, gateway, prompt_ids=target_prompt_ids)

    # 3. Read the after-metric the same way, evaluate, persist the verdict.
    with SessionLocal() as session:
        after = _self_metric(
            session, account_id, scan_after_id, target_prompt_ids, brand
        )
        result = evaluate(before, after)
        row = VerificationRepository(session).create(
            account_id=account_id,
            asset_id=asset_id,
            scan_before_id=scan_before_id,
            scan_after_id=scan_after_id,
            before_metrics=before.model_dump(),
            after_metrics=after.model_dump(),
            confidence=result.confidence,
            verdict=result.verdict,
        )
        outcome = VerificationOutcome(
            verification_id=row.id,
            asset_id=asset_id,
            scan_before_id=scan_before_id,
            scan_after_id=scan_after_id,
            result=result,
            target_prompt_ids=target_prompt_ids,
        )
        session.commit()

    return {
        "verification_id": str(outcome.verification_id),
        "asset_id": str(asset_id),
        "verdict": result.verdict,
        "delta": result.delta,
        "confidence": result.confidence,
        "before": before.model_dump(),
        "after": after.model_dump(),
        "scan_before_id": str(scan_before_id) if scan_before_id else None,
        "scan_after_id": str(scan_after_id),
        "target_prompt_ids": [str(p) for p in target_prompt_ids],
        "notes": result.notes,
    }


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)
