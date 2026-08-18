# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Execution stage — rank gaps (Plan) and generate finished fixes (Execute)."""

from app.pipeline.execution.stage import ExecutionStage, generate_top_fix

__all__ = ["ExecutionStage", "generate_top_fix"]
