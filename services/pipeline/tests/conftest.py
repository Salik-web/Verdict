"""Shared test setup.

Sets the required secret before app modules import their settings. DATABASE_URL
falls back to the Settings default (local infra), so the repository integration
test points at the docker Postgres unless overridden.
"""

import os

os.environ.setdefault("INTERNAL_SHARED_SECRET", "test-secret-12345678")
