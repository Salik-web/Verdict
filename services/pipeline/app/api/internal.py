# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Internal endpoints, guarded by the shared-secret dependency.

/internal/ping proves the authenticated path. The rest are the triggers the TS
API calls; each validates the row exists for the tenant (shared-DB contract) and
enqueues Celery work:

  scans/run          -> the FULL pipeline chain (monitor -> diagnose -> execute)
  diagnoses/run      -> just the Diagnosis stage (re-run one stage)
  executions/run     -> just the Plan+Execute stage
  verifications/run  -> the Verification re-measure for one shipped asset
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app import __version__
from app.api.schemas import HealthResponse
from app.core.security import require_internal_secret
from app.db.base import SessionLocal
from app.db.repositories import AssetRepository, LlmCostRepository, ScanRepository

router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(require_internal_secret)],
)


@router.get("/ping", response_model=HealthResponse)
async def ping() -> HealthResponse:
    """Authenticated liveness check for internal callers."""
    return HealthResponse(service="pipeline", version=__version__)


@router.get("/costs")
async def costs(account_id: uuid.UUID, days: int = 30) -> dict:
    """Surface llm_cost_log as a tenant-scoped, pre-aggregated cost roll-up for
    the last `days` (mock vs real split + per-model breakdown). Internal/ops view;
    the shared-secret dependency on the router guards it."""
    since = datetime.now(UTC) - timedelta(days=max(1, days))
    with SessionLocal() as session:
        return LlmCostRepository(session).summary(account_id, since=since)


class ScanRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scan_id: uuid.UUID
    account_id: uuid.UUID


class ScanRunResponse(BaseModel):
    accepted: bool
    scan_id: uuid.UUID
    task_id: str | None = None


def _require_scan(account_id: uuid.UUID, scan_id: uuid.UUID) -> None:
    with SessionLocal() as session:
        scan = ScanRepository(session).get(account_id, scan_id)
    if scan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="scan not found for this account",
        )


@router.post("/scans/run", response_model=ScanRunResponse, status_code=202)
async def run_scan(body: ScanRunRequest) -> ScanRunResponse:
    """Accept a scan trigger from the TS API and run the FULL pipeline.

    Validates the scan row exists for that tenant (shared-DB contract check),
    then dispatches the Celery chain: monitor -> diagnose -> plan+execute ->
    finalize. Verification is not chained (it's scheduled after a delay).
    """
    _require_scan(body.account_id, body.scan_id)

    # Imported here so the FastAPI app doesn't require a broker connection just
    # to import; enqueue needs Redis (from infra) to be up.
    from app.pipeline.tasks import start_pipeline

    task_id = start_pipeline(body.scan_id, body.account_id)
    return ScanRunResponse(accepted=True, scan_id=body.scan_id, task_id=task_id)


@router.post("/diagnoses/run", response_model=ScanRunResponse, status_code=202)
async def run_diagnosis(body: ScanRunRequest) -> ScanRunResponse:
    """Re-run ONLY the Diagnosis stage for an existing scan."""
    _require_scan(body.account_id, body.scan_id)

    from app.pipeline.tasks import run_diagnosis_task

    async_result = run_diagnosis_task.delay(str(body.scan_id), str(body.account_id))
    return ScanRunResponse(accepted=True, scan_id=body.scan_id, task_id=async_result.id)


@router.post("/executions/run", response_model=ScanRunResponse, status_code=202)
async def run_execution(body: ScanRunRequest) -> ScanRunResponse:
    """Re-run ONLY the Plan+Execute stage for an existing scan."""
    _require_scan(body.account_id, body.scan_id)

    from app.pipeline.tasks import run_execution_task

    async_result = run_execution_task.delay(str(body.scan_id), str(body.account_id))
    return ScanRunResponse(accepted=True, scan_id=body.scan_id, task_id=async_result.id)


@router.get("/engines")
async def engines() -> dict:
    """Which measurement engines this deployment can actually call, and why not.

    Read-only status, never a key-entry surface: in a self-hosted install keys
    belong in .env, and an API that accepted them would invite putting secrets
    somewhere they can be read back. This exists so a user with no keys sees
    "set PERPLEXITY_API_KEY" instead of watching a scan fail.
    """
    from app.gateway import get_gateway
    from app.gateway.availability import all_task_statuses

    gateway = get_gateway()
    statuses = all_task_statuses(gateway.mode, gateway.config)
    return {
        "mode": gateway.mode,
        "engines": [
            {
                "task": s.task,
                "label": s.label,
                "provider": s.provider,
                "model": s.model,
                "available": s.available,
                "reason": s.reason,
                "missing_key_env": s.missing_key_env,
                # Only measurement engines matter for "can I run a scan"; the
                # rest are internal tasks the UI should not present as engines.
                "is_measurement": s.task.startswith("measurement"),
            }
            for s in statuses
        ],
    }


class PromptGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: uuid.UUID
    count: int | None = None
    category: str | None = None


@router.post("/prompts/generate")
async def generate_prompts(body: PromptGenerateRequest) -> dict:
    """Generate a buyer-intent prompt pack for an account and store it.

    Synchronous on purpose: it is one model call, it happens once during
    onboarding, and returning the prompts inline lets the caller show them
    immediately instead of polling a job. Safe to call twice — prompts the
    account already has are skipped.
    """
    from app.pipeline.monitor.prompt_runner import (
        PromptGenerationUnavailable,
        generate_and_store_prompts,
    )

    try:
        return generate_and_store_prompts(
            body.account_id, count=body.count, category=body.category
        )
    except PromptGenerationUnavailable as exc:
        # 503: the deployment is missing a key, which the operator can fix. This
        # is not a bad request and not an internal error.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


class VerificationRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: uuid.UUID
    account_id: uuid.UUID


class VerificationRunResponse(BaseModel):
    accepted: bool
    asset_id: uuid.UUID
    task_id: str | None = None


@router.post(
    "/verifications/run", response_model=VerificationRunResponse, status_code=202
)
async def run_verification(body: VerificationRunRequest) -> VerificationRunResponse:
    """Accept a verification trigger from the TS API and enqueue the re-scan.

    Validates the asset exists for that tenant (shared-DB contract check), then
    dispatches a Celery job that re-runs the asset's target prompts and records an
    honest before/after verdict.
    """
    with SessionLocal() as session:
        asset = AssetRepository(session).get(body.account_id, body.asset_id)
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="asset not found for this account",
        )

    from app.pipeline.tasks import run_verification_task

    async_result = run_verification_task.delay(str(body.asset_id), str(body.account_id))
    return VerificationRunResponse(
        accepted=True, asset_id=body.asset_id, task_id=async_result.id
    )
