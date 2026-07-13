"""Runner: the DB-facing orchestration around the pure Monitor stage.

Loads a ScanContext via repositories, drives the scan lifecycle
(pending -> running -> completed/failed), runs the stage, and persists mentions +
share_of_voice. All model calls happen inside the stage through the gateway, so
this works in mock mode with no API keys.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.db.base import SessionLocal
from app.db.repositories import (
    AccountRepository,
    CompetitorRepository,
    MentionRepository,
    PromptRepository,
    ScanRepository,
    ShareOfVoiceRepository,
)
from app.gateway import Gateway
from app.pipeline.contracts import CompetitorRef, PromptRef, ScanContext
from app.pipeline.monitor.config import get_monitor_config
from app.pipeline.monitor.stage import run_monitor


def load_scan_context(
    session,
    account_id: uuid.UUID,
    scan_id: uuid.UUID,
    prompt_ids: list[uuid.UUID] | None = None,
) -> ScanContext:
    scan = ScanRepository(session).get(account_id, scan_id)
    if scan is None:
        raise ValueError(f"scan {scan_id} not found for account {account_id}")

    account = AccountRepository(session).get_by_id(account_id)
    if account is None:
        raise ValueError(f"account {account_id} not found")

    prompts = PromptRepository(session).list_by_account(account_id, active_only=True)
    if prompt_ids is not None:
        # Verification re-runs a shipped asset's EXACT target prompts.
        wanted = set(prompt_ids)
        prompts = [p for p in prompts if p.id in wanted]
    if not prompts:
        raise ValueError("account has no active prompts to scan")

    competitors = CompetitorRepository(session).list_by_account(account_id)
    cfg = get_monitor_config()

    return ScanContext(
        scan_id=scan_id,
        account_id=account_id,
        brand_name=account.brand_name or account.name,
        brand_aliases=list(account.brand_aliases or []),
        competitors=[
            CompetitorRef(
                id=c.id, name=c.name, aliases=list(c.aliases or []), is_self=c.is_self
            )
            for c in competitors
        ],
        prompts=[PromptRef(id=p.id, text=p.text) for p in prompts],
        engines=[e.name for e in cfg.engines],
        repeats=cfg.repeats,
    )


def run_scan(
    account_id: uuid.UUID | str,
    scan_id: uuid.UUID | str,
    gateway: Gateway | None = None,
    prompt_ids: list[uuid.UUID] | None = None,
) -> dict[str, Any]:
    account_id = _as_uuid(account_id)
    scan_id = _as_uuid(scan_id)

    with SessionLocal() as session:
        context = load_scan_context(session, account_id, scan_id, prompt_ids)
        ScanRepository(session).mark_running(account_id, scan_id, context.engines)
        session.commit()

    try:
        output = run_monitor(context, gateway)
        with SessionLocal() as session:
            n_mentions = MentionRepository(session).bulk_insert(
                account_id, scan_id, output.mentions
            )
            n_sov = ShareOfVoiceRepository(session).insert_many(
                account_id, scan_id, output.share_of_voice
            )
            stats = {
                "prompts": len(context.prompts),
                "engines": context.engines,
                "repeats": context.repeats,
                "mentions": n_mentions,
                "sov_rows": n_sov,
            }
            ScanRepository(session).mark_completed(account_id, scan_id, stats)
            session.commit()
        return stats
    except Exception as exc:
        with SessionLocal() as session:
            ScanRepository(session).mark_failed(account_id, scan_id, str(exc))
            session.commit()
        raise


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)
