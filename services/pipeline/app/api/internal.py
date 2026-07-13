"""Internal endpoints, guarded by the shared-secret dependency.

/internal/ping proves the authenticated path; /internal/scans/run is the scan
trigger the TS API calls. It validates the scan exists for the tenant (shared-DB
contract) and enqueues the Monitor stage as a Celery job.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app import __version__
from app.api.schemas import HealthResponse
from app.core.security import require_internal_secret
from app.db.base import SessionLocal
from app.db.repositories import AssetRepository, ScanRepository

router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(require_internal_secret)],
)


@router.get("/ping", response_model=HealthResponse)
async def ping() -> HealthResponse:
    """Authenticated liveness check for internal callers."""
    return HealthResponse(service="pipeline", version=__version__)


class ScanRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scan_id: uuid.UUID
    account_id: uuid.UUID


class ScanRunResponse(BaseModel):
    accepted: bool
    scan_id: uuid.UUID
    task_id: str | None = None


@router.post("/scans/run", response_model=ScanRunResponse, status_code=202)
async def run_scan(body: ScanRunRequest) -> ScanRunResponse:
    """Accept a scan trigger from the TS API and enqueue the Monitor stage.

    Validates the scan row exists for that tenant (shared-DB contract check),
    then dispatches a Celery job that runs the LangGraph monitor stage and
    writes mentions + share_of_voice.
    """
    with SessionLocal() as session:
        scan = ScanRepository(session).get(body.account_id, body.scan_id)
    if scan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="scan not found for this account",
        )

    # Imported here so the FastAPI app doesn't require a broker connection just
    # to import; enqueue needs Redis (from infra) to be up.
    from app.pipeline.tasks import run_scan_task

    async_result = run_scan_task.delay(str(body.scan_id), str(body.account_id))
    return ScanRunResponse(accepted=True, scan_id=body.scan_id, task_id=async_result.id)


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
