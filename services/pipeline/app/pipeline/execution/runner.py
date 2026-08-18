# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Runner: DB-facing orchestration around the pure Execution stage.

Loads a GeneratorContext + open gaps via repositories, runs the stage, writes the
asset content to a downloadable artifact file, and persists the assets row
(tagged with target_prompt_ids). Rejected assets are still stored, flagged.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from app.db.base import SessionLocal
from app.db.repositories import (
    AccountRepository,
    AssetRepository,
    CompetitorRepository,
    GapRepository,
    PromptRepository,
    VerifiedFactRepository,
)
from app.gateway import Gateway
from app.pipeline.execution.base import Generator
from app.pipeline.execution.config import PIPELINE_ROOT, get_execution_config
from app.pipeline.execution.contracts import (
    CompetitorRef,
    GapInput,
    GeneratorContext,
    VerifiedFactRef,
)
from app.pipeline.execution.facts_gate import GenerationBlocked
from app.pipeline.execution.stage import generate_top_fix
from app.pipeline.execution.validate import VALIDATOR_VERSION
from app.pipeline.verification.feedback import confidence_overrides_from_history

_COMPARISON_CATEGORIES = {"comparison", "alternatives", "competitive"}


def load_generator_context(
    session, account_id: uuid.UUID, scan_id: uuid.UUID | None = None
) -> GeneratorContext:
    account = AccountRepository(session).get_by_id(account_id)
    if account is None:
        raise ValueError(f"account {account_id} not found")

    competitors = [
        CompetitorRef(name=c.name, domain=c.domain, aliases=list(c.aliases or []))
        for c in CompetitorRepository(session).list_by_account(account_id)
        if not c.is_self
    ]
    # `about`/`competitor` ride in the fact's jsonb value (no schema change), so a
    # competitor's real pricing can be stated rather than invented.
    facts = [
        VerifiedFactRef(
            fact_type=f.fact_type,
            key=f.key,
            display=str((f.value or {}).get("display", "")),
            about=(f.value or {}).get("about", "self"),
            competitor=(f.value or {}).get("competitor"),
        )
        for f in VerifiedFactRepository(session).list_active(account_id)
    ]
    prompts = PromptRepository(session).list_by_account(account_id, active_only=True)
    targeted = [p.id for p in prompts if p.category in _COMPARISON_CATEGORIES]
    target_prompt_ids = targeted or [p.id for p in prompts]

    return GeneratorContext(
        account_id=account_id,
        scan_id=scan_id,
        brand_name=account.brand_name or account.name,
        brand_aliases=list(account.brand_aliases or []),
        target_url=f"https://{account.domain}" if account.domain else None,
        competitors=competitors,
        verified_facts=facts,
        target_prompt_ids=target_prompt_ids,
    )


def load_open_gaps(
    session, account_id: uuid.UUID, scan_id: uuid.UUID | None
) -> list[GapInput]:
    rows = GapRepository(session).list_open(account_id, scan_id)
    return [
        GapInput(
            gap_id=r.id,
            gap_type=r.gap_type,
            fix_type=(r.details or {}).get("fix_type", ""),
            prompt_ids=[r.prompt_id] if r.prompt_id else [],
            details=r.details or {},
        )
        for r in rows
    ]


def asset_metadata(asset, plan_score: float) -> dict[str, Any]:
    """What gets stored alongside an asset row.

    `validator_version` is the load-bearing entry: without it a stored `passed` is
    a claim of unknown vintage, and revalidate.py cannot tell an asset the current
    validator approved from one generated before the validator existed.
    """
    return {
        "fix_type": asset.fix_type,
        "content_kind": asset.content_kind,
        "validator_version": VALIDATOR_VERSION,
        "schema_jsonld": asset.schema_jsonld,
        "claims": [c.model_dump() for c in asset.claims],
        "violations": asset.violations,
        "plan_score": plan_score,
    }


def _write_artifact(account_id: uuid.UUID, asset_id: uuid.UUID, asset) -> str:
    ext = "html" if asset.content_kind == "html" else "txt"
    rel = (
        Path(get_execution_config().artifacts_dir)
        / str(account_id)
        / f"{asset_id}.{ext}"
    )
    path = PIPELINE_ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(asset.content, encoding="utf-8")
    return str(rel).replace("\\", "/")


def run_execution(
    account_id: uuid.UUID | str,
    *,
    scan_id: uuid.UUID | str | None = None,
    gateway: Gateway | None = None,
    registry: dict[str, Generator] | None = None,
) -> dict[str, Any]:
    """Plan the account's open gaps and, if a generator exists for the top fix,
    build and persist the asset.

    `registry=None` discovers generators (entry points + in-process
    registrations); pass an explicit mapping to compose the runner without
    touching global state. A stock install discovers none, so the ordinary
    result is a ranked backlog and `skipped_generation`.
    """
    account_id = _as_uuid(account_id)
    scan_id = _as_uuid(scan_id) if scan_id else None

    with SessionLocal() as session:
        context = load_generator_context(session, account_id, scan_id)
        gaps = load_open_gaps(session, account_id, scan_id)
        # Close the loop: past verification outcomes reweight the planner's
        # confidence for gap_types we've already shipped fixes for.
        overrides = confidence_overrides_from_history(session, account_id)
    if not gaps:
        # A clean site is a legitimate result, not an error.
        return {"skipped": True, "reason": "no open gaps to execute", "backlog": []}

    try:
        output = generate_top_fix(
            gaps,
            context,
            gateway,
            registry=registry,
            confidence_overrides=overrides,
        )
    except GenerationBlocked as blocked:
        # Not a failure: we deliberately refused to publish something hollow. The
        # gaps stay open, and the customer gets an actionable reason.
        return {
            "blocked": True,
            "reason": blocked.reason,
            "detail": blocked.detail,
            "backlog": blocked.detail.get("backlog", []),
        }

    if not output.produced_asset:
        # The ordinary path in this distribution: gaps were found and ranked,
        # but no generator is registered to build the top fix. The backlog IS
        # the deliverable here, so it must be reported, not swallowed.
        return {
            "skipped_generation": True,
            "reason": output.reason,
            "unsupported_fix_types": output.unsupported_fix_types,
            "backlog": [(i.fix_type, i.score) for i in output.backlog.items],
        }

    asset = output.asset

    asset_id = uuid.uuid4()
    content_ref = _write_artifact(account_id, asset_id, asset)

    with SessionLocal() as session:
        AssetRepository(session).create(
            account_id=account_id,
            asset_id=asset_id,
            gap_id=output.plan_item.gap_ids[0] if output.plan_item.gap_ids else None,
            type=asset.asset_type,
            title=asset.title,
            content_ref=content_ref,
            metadata=asset_metadata(asset, output.plan_item.score),
            target_prompt_ids=asset.target_prompt_ids,
            status=asset.status,
            validation_state=asset.validation_state,
        )
        session.commit()

    return {
        "asset_id": str(asset_id),
        "type": asset.asset_type,
        "status": asset.status,
        "validation_state": asset.validation_state,
        "content_ref": content_ref,
        "target_prompt_ids": [str(p) for p in asset.target_prompt_ids],
        "violations": asset.violations,
        "backlog": [(i.fix_type, i.score) for i in output.backlog.items],
    }


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)
