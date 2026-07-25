"""Shared test setup.

Sets the required secret before app modules import their settings. DATABASE_URL
falls back to the Settings default (local infra), so the repository integration
test points at the docker Postgres unless overridden.
"""

import os

os.environ.setdefault("INTERNAL_SHARED_SECRET", "test-secret-12345678")

# Tests ALWAYS run in mock mode, immune to the developer's .env (which is set to
# `dev` for a real Gemini run). Without this, integration tests that use the
# default gateway (e.g. run_scan(gateway=None)) would hit live provider APIs and
# spend real quota. setdefault, so an explicit `GATEWAY_MODE=dev pytest` still
# wins if someone truly wants it; os.environ also outranks the .env file value.
os.environ.setdefault("GATEWAY_MODE", "mock")
