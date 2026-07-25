"""Verification scheduling: shipped assets come due after the config delay.

Verification is deliberately not chained onto a scan — the beat picks assets up
once `schedule.delay_hours` has passed. `delay_hours: 0` makes them due
immediately, which is the switch for testing the loop without waiting a week.

Uses a THROWAWAY account, not the demo one: the sweep batches the oldest N due
assets per account, and a long-lived dev DB accumulates dozens of unverified
demo assets, which would push a freshly-made fixture out of the batch. Isolation
keeps this about the delay logic.

Requires the migrated DB; skips cleanly if unreachable.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import OperationalError

from app.db.base import SessionLocal
from app.db.models import Account, Asset
from app.pipeline.verification.config import get_verification_config
from app.pipeline.verification.schedule import enqueue_due_verifications


def _db_ready() -> bool:
    try:
        with SessionLocal() as s:
            s.connection()
        return True
    except OperationalError:
        return False


def _cfg(delay_hours: float):
    """The real config with only the delay overridden."""
    base = get_verification_config()
    return base.model_copy(
        update={
            "schedule": base.schedule.model_copy(update={"delay_hours": delay_hours})
        }
    )


@pytest.fixture
def shipped():
    """A throwaway account with exactly one asset, shipped 5 minutes ago.

    created_at is set EXPLICITLY rather than left to the DB default: with
    `delay_hours: 0` the cutoff is "now" from the Python clock, so a just-inserted
    row races the DB clock and can look not-yet-due.
    """
    if not _db_ready():
        pytest.skip("database unreachable — run docker compose up + db:migrate")

    tag = uuid.uuid4().hex[:8]
    with SessionLocal() as s:
        account = Account(
            name=f"Verify Sched {tag}",
            slug=f"verify-sched-{tag}",
            brand_name="Verify Sched",
            plan="enterprise",
        )
        s.add(account)
        s.flush()
        account_id = account.id

        asset_id = uuid.uuid4()
        s.add(
            Asset(
                id=asset_id,
                account_id=account_id,
                type="comparison_page",
                title="Scheduling fixture",
                content_ref=f"artifacts/{account_id}/{asset_id}.html",
                metadata_={},
                target_prompt_ids=[uuid.uuid4()],
                status="validated",
                validation_state="passed",
                created_at=datetime.now(UTC) - timedelta(minutes=5),
            )
        )
        s.commit()

    yield account_id, asset_id

    with SessionLocal() as s:
        acct = s.get(Account, account_id)
        if acct is not None:
            s.delete(acct)  # cascades to the asset
            s.commit()


def test_delay_zero_makes_a_shipped_asset_due_now(shipped):
    _, asset_id = shipped
    calls: list[tuple[str, str]] = []

    result = enqueue_due_verifications(
        enqueue=lambda a, acct: calls.append((a, acct)),
        cfg=_cfg(0),
    )

    assert result["delay_hours"] == 0
    assert any(a == str(asset_id) for a, _ in calls), "asset shipped 5min ago is due"


def test_a_long_delay_leaves_a_just_shipped_asset_alone(shipped):
    _, asset_id = shipped
    calls: list[tuple[str, str]] = []

    enqueue_due_verifications(
        enqueue=lambda a, acct: calls.append((a, acct)),
        cfg=_cfg(24 * 365),  # a year — nothing shipped that long ago
    )

    assert not any(a == str(asset_id) for a, _ in calls)
