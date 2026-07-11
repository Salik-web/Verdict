"""Runner: DB-facing orchestration around the pure Diagnosis stage.

Loads a DiagnosisContext via repositories, runs the stage, and persists the
resulting Gaps. `target_url` defaults to the account's domain but can be
overridden (the demo account's domain is a non-resolving example).
"""

from __future__ import annotations

import uuid
from typing import Any

from app.db.base import SessionLocal
from app.db.repositories import AccountRepository, GapRepository
from app.gateway import Gateway
from app.pipeline.diagnosis.contracts import DiagnosisContext
from app.pipeline.diagnosis.fetcher import Fetcher
from app.pipeline.diagnosis.stage import diagnose


def load_diagnosis_context(
    session,
    account_id: uuid.UUID,
    *,
    scan_id: uuid.UUID | None,
    target_url: str | None,
    competitor_urls: list[str] | None,
) -> DiagnosisContext:
    account = AccountRepository(session).get_by_id(account_id)
    if account is None:
        raise ValueError(f"account {account_id} not found")
    url = target_url or (f"https://{account.domain}" if account.domain else None)
    if not url:
        raise ValueError("no target_url given and account has no domain")
    return DiagnosisContext(
        account_id=account_id,
        scan_id=scan_id,
        brand_name=account.brand_name or account.name,
        brand_aliases=list(account.brand_aliases or []),
        target_url=url,
        competitor_urls=competitor_urls or [],
    )


def run_diagnosis(
    account_id: uuid.UUID | str,
    *,
    scan_id: uuid.UUID | str | None = None,
    target_url: str | None = None,
    competitor_urls: list[str] | None = None,
    fetcher: Fetcher | None = None,
    gateway: Gateway | None = None,
) -> dict[str, Any]:
    account_id = _as_uuid(account_id)
    scan_id = _as_uuid(scan_id) if scan_id else None

    with SessionLocal() as session:
        context = load_diagnosis_context(
            session,
            account_id,
            scan_id=scan_id,
            target_url=target_url,
            competitor_urls=competitor_urls,
        )

    output = diagnose(context, fetcher, gateway)

    with SessionLocal() as session:
        n_gaps = GapRepository(session).bulk_insert(account_id, scan_id, output.gaps)
        session.commit()

    return {
        "target_url": context.target_url,
        "findings": len(output.findings),
        "gaps": n_gaps,
        "blocked_search_bots": output.bot_audit.blocked_search_bots,
        "traps": output.bot_audit.traps_triggered,
    }


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)
