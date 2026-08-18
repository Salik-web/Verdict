# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Pydantic models for HTTP boundaries.

The HealthResponse mirrors packages/shared/schemas/health.schema.json and the
TS HealthResponse type — keep all three in lockstep.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"] = "ok"
    service: str
    version: str
    time: datetime = Field(default_factory=lambda: datetime.now(UTC))
