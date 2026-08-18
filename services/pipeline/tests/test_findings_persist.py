# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Findings are persisted, not counted.

`run_diagnosis` returned `len(output.findings)` and threw the findings away, so
the only surviving record of a scan's checks was the subset that became gaps.
Every check that concluded "no problem here" left nothing behind.

Skips cleanly if the DB is unreachable, like the other integration tests.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import OperationalError

from app.db.base import SessionLocal
from app.db.models import Scan
from app.db.repositories import FindingRepository, GapRepository
from app.gateway.cost import NullCostSink
from app.gateway.gateway import build_gateway
from app.gateway.models_config import get_models_config
from app.pipeline.diagnosis.fetcher import FakeFetcher, FetchResult
from app.pipeline.diagnosis.runner import run_diagnosis

DEMO_ACCOUNT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
TARGET = "https://8.8.8.8/"
ROBOTS = f"User-agent: *\nDisallow:\nSitemap: {TARGET}sitemap.xml\n"
HOME = "<html><body><h1>Acme</h1><p>Analytics.</p></body></html>"
SITEMAP = (
    "<?xml version='1.0'?><urlset>"
    f"<url><loc>{TARGET}</loc></url>"
    f"<url><loc>{TARGET}pricing</loc></url>"
    f"<url><loc>{TARGET}compare/acme-vs-globex</loc></url>"
    "</urlset>"
)


def _db_ready() -> bool:
    try:
        with SessionLocal() as s:
            s.connection()
        return True
    except OperationalError:
        return False


def _run() -> tuple[uuid.UUID, dict]:
    with SessionLocal() as s:
        scan = Scan(account_id=DEMO_ACCOUNT_ID, status="pending", engine_set=[])
        s.add(scan)
        s.commit()
        scan_id = scan.id

    def page(url: str, body: str, ctype: str) -> FetchResult:
        return FetchResult(
            url=url,
            final_url=url,
            status=200,
            ok=True,
            text=body,
            headers={"content-type": ctype},
            content_type=ctype,
        )

    fetcher = FakeFetcher(
        {
            TARGET: page(TARGET, HOME, "text/html"),
            f"{TARGET}robots.txt": page(f"{TARGET}robots.txt", ROBOTS, "text/plain"),
            f"{TARGET}sitemap.xml": page(
                f"{TARGET}sitemap.xml", SITEMAP, "application/xml"
            ),
        }
    )
    result = run_diagnosis(
        DEMO_ACCOUNT_ID,
        scan_id=scan_id,
        target_url=TARGET,
        fetcher=fetcher,
        gateway=build_gateway(
            mode="mock", cost_sink=NullCostSink(), config=get_models_config()
        ),
    )
    return scan_id, result


def test_every_finding_is_persisted_not_just_the_gaps():
    if not _db_ready():
        pytest.skip("database unreachable — run docker compose up + db:migrate/seed")
    scan_id, result = _run()

    with SessionLocal() as s:
        findings = FindingRepository(s).list_for_scan(DEMO_ACCOUNT_ID, scan_id)
        gaps = GapRepository(s).list_for_scan(DEMO_ACCOUNT_ID, scan_id)

    assert len(findings) == result["findings"]
    # The point: strictly MORE findings than gaps — the passes survive too.
    assert len(findings) > len(gaps)
    assert any(f.ok for f in findings), "no passing check was stored"
    assert {f.status for f in findings} <= {
        "confirmed_present",
        "confirmed_absent",
        "check_failed",
    }


def test_a_passing_check_carries_its_working():
    if not _db_ready():
        pytest.skip("database unreachable")
    scan_id, _ = _run()

    with SessionLocal() as s:
        findings = FindingRepository(s).list_for_scan(DEMO_ACCOUNT_ID, scan_id)

    comparison = next(f for f in findings if f.code == "comparison_page_present")
    assert comparison.ok is True
    assert comparison.gap_type is None
    # THE regression this closes: the record can answer "why no gap?" on its own.
    assert comparison.detail["basis"] == "sitemap"
    assert comparison.detail["matches"] == 1
    assert comparison.detail["match_examples"] == [f"{TARGET}compare/acme-vs-globex"]
    assert comparison.detail["sitemap"]["source"] == "robots_directive"
    assert comparison.detail["sitemap"]["urls_read"] == 3


def test_evidence_round_trips_through_jsonb():
    if not _db_ready():
        pytest.skip("database unreachable")
    scan_id, _ = _run()

    with SessionLocal() as s:
        findings = FindingRepository(s).list_for_scan(DEMO_ACCOUNT_ID, scan_id)

    with_evidence = [f for f in findings if f.evidence]
    assert with_evidence, "no finding carried evidence"
    sample = with_evidence[0].evidence[0]
    # The Evidence contract, intact after a JSONB round trip.
    assert {"url", "status", "fetched_at", "bytes", "truncated"} <= set(sample)


def test_history_answers_the_regression_question():
    """ "This check used to raise a gap — when did it stop, and on what basis?" is
    the question the old record could not answer at all."""
    if not _db_ready():
        pytest.skip("database unreachable")
    _run()
    _run()

    with SessionLocal() as s:
        rows = FindingRepository(s).history(
            DEMO_ACCOUNT_ID, "comparison_page_present", limit=5
        )
    assert len(rows) >= 2
    assert all(r.detail["basis"] == "sitemap" for r in rows)
