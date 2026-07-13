"""Plan-quota double-check for the pipeline.

The TS quota middleware is the real gate in front of the API; this is
defense-in-depth so an expensive job triggered another way (a scheduled beat, an
internal call) still can't blow past the account's plan. Config-driven caps
(config/quotas.yaml), counted as scans created this calendar month (UTC).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.repositories import AccountRepository, ScanRepository
from app.pipeline.schedule.config import QuotaConfig, get_quota_config


class QuotaExceeded(Exception):
    """Raised when an account has used its plan's scan quota for the period."""


def _period_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def usage(session: Session, account_id: uuid.UUID | str, now: datetime) -> int:
    return ScanRepository(session).count_since(account_id, _period_start(now))


def check_quota(
    session: Session,
    account_id: uuid.UUID | str,
    *,
    plan: str | None = None,
    now: datetime | None = None,
    cfg: QuotaConfig | None = None,
) -> None:
    """Raise QuotaExceeded if the account is at/over its monthly scan cap. `plan`
    is looked up from the account when not supplied."""
    cfg = cfg or get_quota_config()
    now = now or datetime.now(UTC)

    if plan is None:
        account = AccountRepository(session).get_by_id(account_id)
        plan = account.plan if account is not None else None

    cap = cfg.monthly_scans(plan)
    used = usage(session, account_id, now)
    if used >= cap:
        raise QuotaExceeded(
            f"account {account_id} used {used}/{cap} scans this period "
            f"(plan={plan!r})"
        )
