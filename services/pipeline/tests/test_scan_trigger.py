"""/internal/scans/run: shared-secret guard + payload validation + DB check."""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.core.security import INTERNAL_SECRET_HEADER
from app.main import app

client = TestClient(app)
SECRET = os.environ["INTERNAL_SHARED_SECRET"]
DEMO_ACCOUNT_ID = "00000000-0000-0000-0000-000000000001"


def _db_available() -> bool:
    from app.db.base import SessionLocal

    try:
        with SessionLocal() as s:
            s.connection()
        return True
    except OperationalError:
        return False


def test_requires_secret() -> None:
    res = client.post(
        "/internal/scans/run",
        json={"scan_id": str(uuid.uuid4()), "account_id": DEMO_ACCOUNT_ID},
    )
    assert res.status_code == 401


def test_rejects_bad_payload() -> None:
    res = client.post(
        "/internal/scans/run",
        headers={INTERNAL_SECRET_HEADER: SECRET},
        json={"scan_id": "not-a-uuid", "account_id": DEMO_ACCOUNT_ID},
    )
    assert res.status_code == 422


def test_unknown_scan_is_404() -> None:
    if not _db_available():
        pytest.skip("database unreachable")
    res = client.post(
        "/internal/scans/run",
        headers={INTERNAL_SECRET_HEADER: SECRET},
        json={"scan_id": str(uuid.uuid4()), "account_id": DEMO_ACCOUNT_ID},
    )
    assert res.status_code == 404
