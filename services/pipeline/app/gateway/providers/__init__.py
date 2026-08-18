# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Model provider adapters.

Adding an engine is genuinely a drop-in: create a module here with a class
decorated `@register_provider("<type>")` and set that `<type>` in
config/models.yaml. The gateway discovers it — no edits here, in gateway.py, or to
any provider-type enum (there isn't one).

Concrete adapters are intentionally NOT imported eagerly below: the registry
discovers them from disk, so the import list can't drift from what's on disk.
"""

from app.gateway.providers.base import Provider
from app.gateway.providers.http import ProviderHTTPError, ProviderRateLimited
from app.gateway.providers.registry import (
    build_providers,
    ensure_registered,
    register_provider,
    registered_types,
)

__all__ = [
    "Provider",
    "ProviderHTTPError",
    "ProviderRateLimited",
    "register_provider",
    "build_providers",
    "ensure_registered",
    "registered_types",
]
