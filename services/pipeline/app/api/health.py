# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Public health check — no auth, used by Docker/load balancers."""

from __future__ import annotations

from fastapi import APIRouter

from app import __version__
from app.api.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["health"])
async def health() -> HealthResponse:
    return HealthResponse(service="pipeline", version=__version__)
