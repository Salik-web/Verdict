"""Internal endpoints, guarded by the shared-secret dependency.

/internal/ping proves the authenticated path; /internal/scans/run is the scan
trigger the TS API calls. The actual pipeline stages (monitor/diagnose/execute/
verify) land in the next phase — for now the trigger validates the scan exists
in the shared DB (proving the cross-service contract) and acknowledges.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app import __version__
from app.api.schemas import HealthResponse
from app.core.security import require_internal_secret
from app.db.base import SessionLocal
from app.db.repositories import ScanRepository

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


@router.post("/scans/run", response_model=ScanRunResponse, status_code=202)
async def run_scan(body: ScanRunRequest) -> ScanRunResponse:
    """Accept a scan trigger from the TS API.

    Validates the scan row exists for that tenant (shared-DB contract check).
    Orchestration (Celery + LangGraph stages) attaches here next phase.
    """
    with SessionLocal() as session:
        scan = ScanRepository(session).get(body.account_id, body.scan_id)
    if scan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="scan not found for this account",
        )
    return ScanRunResponse(accepted=True, scan_id=body.scan_id)
