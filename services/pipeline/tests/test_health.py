"""Proves the health endpoints and the internal-secret guard.

Sets a known secret in the environment before importing the app so the cached
settings pick it up.
"""

import os

os.environ.setdefault("INTERNAL_SHARED_SECRET", "test-secret-12345678")

from fastapi.testclient import TestClient  # noqa: E402

from app.core.security import INTERNAL_SECRET_HEADER  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
SECRET = os.environ["INTERNAL_SHARED_SECRET"]


def test_public_health_ok() -> None:
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["service"] == "pipeline"


def test_internal_ping_requires_secret() -> None:
    assert client.get("/internal/ping").status_code == 401
    bad = client.get("/internal/ping", headers={INTERNAL_SECRET_HEADER: "nope"})
    assert bad.status_code == 401


def test_internal_ping_accepts_valid_secret() -> None:
    res = client.get("/internal/ping", headers={INTERNAL_SECRET_HEADER: SECRET})
    assert res.status_code == 200
    assert res.json()["service"] == "pipeline"
