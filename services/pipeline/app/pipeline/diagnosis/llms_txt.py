# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""/llms.txt detection: fetch it, flag if missing or stale."""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse, urlunparse

from app.pipeline.diagnosis.config import get_diagnosis_config
from app.pipeline.diagnosis.contracts import Finding
from app.pipeline.diagnosis.fetcher import Fetcher
from app.pipeline.diagnosis.probe import probe


def llms_txt_url_for(target_url: str) -> str:
    p = urlparse(target_url)
    return urlunparse((p.scheme, p.netloc, "/llms.txt", "", "", ""))


def check_llms_txt(fetcher: Fetcher, target_url: str) -> Finding:
    stale_days = get_diagnosis_config().llms_txt.get("stale_days", 180)
    url = llms_txt_url_for(target_url)
    p = probe(fetcher, url)
    evidence = [p.evidence]

    # Refused or unreachable (403/429/5xx/timeout): we learned nothing. Reporting
    # "missing" here would be a confident claim about a file we never saw.
    if p.failed:
        status = p.evidence.status
        return Finding(
            layer="llms_txt",
            code="llms_txt_check_failed",
            ok=True,  # not a pass, but never a gap — see status
            severity="info",
            summary=(
                f"Could not determine whether /llms.txt exists "
                f"({'HTTP ' + str(status) if status else p.evidence.note})."
            ),
            status="check_failed",
            confidence=0.0,
            evidence=evidence,
        )

    result = p.result
    if p.absent or result is None or not (result.text or "").strip():
        return Finding(
            layer="llms_txt",
            code="llms_txt_missing",
            ok=False,
            severity="medium",
            summary="No /llms.txt found — nothing guides AI assistants on your site.",
            gap_type="missing_llms_txt",
            status="confirmed_absent",
            confidence=1.0,
            evidence=evidence,
        )

    last_modified = result.headers.get("last-modified")
    if last_modified:
        try:
            modified = parsedate_to_datetime(last_modified)
            age_days = (datetime.now(UTC) - modified).days
            if age_days > stale_days:
                return Finding(
                    layer="llms_txt",
                    code="llms_txt_stale",
                    ok=False,
                    severity="low",
                    summary=f"/llms.txt is stale ({age_days} days old).",
                    gap_type="missing_llms_txt",
                    detail={"age_days": age_days},
                    status="confirmed_absent",  # present but stale = actionable
                    confidence=1.0,
                    evidence=evidence,
                )
        except (TypeError, ValueError):
            pass

    return Finding(
        layer="llms_txt",
        code="llms_txt_present",
        ok=True,
        severity="info",
        summary="/llms.txt is present.",
        status="confirmed_present",
        confidence=1.0,
        evidence=evidence,
    )
