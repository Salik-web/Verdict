# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Model gateway — the single module that wraps ALL model calls.

Everything downstream (measurement, processing, generation) goes through
`get_gateway().call(task, messages, ...)`. Mode (mock/dev/prod) and the
task→model mapping live in config/models.yaml, not in code.
"""

from app.gateway.gateway import Gateway, build_gateway, get_gateway
from app.gateway.types import GatewayResponse, Message, Usage

__all__ = [
    "Gateway",
    "build_gateway",
    "get_gateway",
    "GatewayResponse",
    "Message",
    "Usage",
]
