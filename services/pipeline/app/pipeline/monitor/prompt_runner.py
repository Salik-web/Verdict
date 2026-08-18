# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""DB-facing wrapper around prompt auto-generation.

A fresh account starts with zero prompts, and a scan with no prompts measures
nothing — so until this was reachable, every new user had to invent 20-odd
buyer-intent queries by hand before the product could do anything at all. That
was the single largest usability defect for a new user.

`generate_and_store_prompts` loads the account's brand and competitors, asks the
gateway for a prompt pack, drops anything the account already has, and inserts
the rest. It is deliberately synchronous: it is ONE model call, it happens once
during onboarding, and a caller that gets prompts back in the response can show
them immediately instead of polling a job.

Deduplication is case- and whitespace-insensitive so re-running never doubles up
an existing prompt — the endpoint is safe to call twice.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.db.base import SessionLocal
from app.db.repositories import (
    AccountRepository,
    CompetitorRepository,
    PromptRepository,
)
from app.gateway import Gateway, get_gateway
from app.gateway.availability import task_status
from app.pipeline.monitor.prompts import generate_prompts


class PromptGenerationUnavailable(RuntimeError):
    """The generation engine has no usable key in this deployment."""


def _norm(text: str) -> str:
    return " ".join((text or "").split()).casefold()


def generate_and_store_prompts(
    account_id: uuid.UUID | str,
    *,
    count: int | None = None,
    category: str | None = None,
    gateway: Gateway | None = None,
) -> dict[str, Any]:
    account_id = (
        account_id if isinstance(account_id, uuid.UUID) else uuid.UUID(account_id)
    )
    gateway = gateway or get_gateway()

    # Fail with the env var to set, not with a provider stack trace on line one.
    status = task_status("generation", gateway.mode, gateway.config)
    if not status.available:
        raise PromptGenerationUnavailable(f"Cannot generate prompts: {status.reason}")

    with SessionLocal() as session:
        account = AccountRepository(session).get_by_id(account_id)
        if account is None:
            raise ValueError(f"account {account_id} not found")
        brand_name = account.brand_name or account.name
        settings_category = (account.settings or {}).get("category")
        competitors = [
            c.name
            for c in CompetitorRepository(session).list_by_account(account_id)
            if not c.is_self
        ]
        existing = {
            _norm(p.text) for p in PromptRepository(session).list_by_account(account_id)
        }

    generated = generate_prompts(
        gateway,
        account_id=account_id,
        brand_name=brand_name,
        competitors=competitors,
        category=category or settings_category,
        count=count,
    )

    fresh: list[str] = []
    seen = set(existing)
    for text in generated:
        key = _norm(text)
        if not key or key in seen:
            continue
        seen.add(key)
        fresh.append(text.strip())

    created: list[dict[str, Any]] = []
    if fresh:
        with SessionLocal() as session:
            rows = PromptRepository(session).create_many(
                account_id, fresh, prompt_group="auto"
            )
            session.flush()
            created = [{"id": str(r.id), "text": r.text} for r in rows]
            session.commit()

    return {
        "generated": len(generated),
        "created": len(created),
        "skipped_duplicates": len(generated) - len(fresh),
        "prompts": created,
    }
