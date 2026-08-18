# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Internal service-to-service authentication.

Any endpoint depending on ``require_internal_secret`` must receive the
``x-internal-secret`` header matching INTERNAL_SHARED_SECRET, or it is rejected
with 401. Comparison is constant-time to avoid timing leaks.
"""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from app.core.config import get_settings

# Mirror of INTERNAL_SECRET_HEADER in packages/shared.
INTERNAL_SECRET_HEADER = "x-internal-secret"


async def require_internal_secret(
    x_internal_secret: str | None = Header(default=None),
) -> None:
    """FastAPI dependency guarding internal endpoints."""
    expected = get_settings().internal_shared_secret
    if x_internal_secret is None or not hmac.compare_digest(
        x_internal_secret, expected
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing internal secret",
        )
