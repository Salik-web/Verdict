"""Internal endpoints, guarded by the shared-secret dependency.

Phase 1 ships only /internal/ping, which the TS API calls to prove the
authenticated path. Stage trigger endpoints (monitor/diagnose/execute/verify)
get added here in later phases.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app import __version__
from app.api.schemas import HealthResponse
from app.core.security import require_internal_secret

router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(require_internal_secret)],
)


@router.get("/ping", response_model=HealthResponse)
async def ping() -> HealthResponse:
    """Authenticated liveness check for internal callers."""
    return HealthResponse(service="pipeline", version=__version__)
