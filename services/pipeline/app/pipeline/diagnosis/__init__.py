# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Diagnosis stage — find WHY the customer loses (SEO + GEO + crawler audit)."""

from app.pipeline.diagnosis.stage import DiagnosisStage, diagnose

__all__ = ["DiagnosisStage", "diagnose"]
