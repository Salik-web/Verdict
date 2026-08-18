# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Orchestration: the pipeline chain's stages, bookkeeping, and failure mode.

Tasks are executed eagerly with `.apply()` so no broker is needed — the chain's
wiring (order, args) is trivial; what matters is that each stage does its jobs-row
+ scan-stats bookkeeping, that skips are not failures, and that a failure marks
the scan failed and raises (which is what aborts a real chain).

Requires the migrated + seeded DB; skips cleanly if unreachable.
"""

from __future__ import annotations

import uuid
from contextlib import suppress
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import OperationalError

from app.celery_app import celery_app
from app.db.base import SessionLocal
from app.db.models import Asset as AssetRow
from app.db.models import Scan
from app.db.repositories import (
    AccountRepository,
    GapRepository,
    JobRepository,
    ScanRepository,
)
from app.pipeline.tasks import (
    _stage,
    finalize_scan_task,
    run_diagnosis_task,
    run_execution_task,
    run_scan_task,
    start_pipeline,
)

DEMO_ACCOUNT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _db_ready() -> bool:
    try:
        with SessionLocal() as s:
            s.connection()
        return True
    except OperationalError:
        return False


def _new_scan(account_id: uuid.UUID) -> uuid.UUID:
    with SessionLocal() as s:
        scan = Scan(account_id=account_id, status="pending", engine_set=[])
        s.add(scan)
        s.commit()
        return scan.id


def test_chain_stages_run_record_jobs_and_complete_the_scan():
    if not _db_ready():
        pytest.skip("database unreachable — run docker compose up + db:migrate/seed")

    with SessionLocal() as s:
        account = AccountRepository(s).get_by_id(DEMO_ACCOUNT_ID)
        original_plan = account.plan
        account.plan = "enterprise"  # quota headroom on an accumulated dev DB
        s.commit()

    started = datetime.now(UTC)
    scan_id = _new_scan(DEMO_ACCOUNT_ID)
    try:
        # The chain, run stage by stage (monitor is chained -> finalize=False).
        run_scan_task.apply(args=(str(scan_id), str(DEMO_ACCOUNT_ID), False)).get()

        with SessionLocal() as s:
            # Monitor alone must NOT complete the scan — the pipeline isn't done.
            assert ScanRepository(s).get(DEMO_ACCOUNT_ID, scan_id).status == "running"

        run_diagnosis_task.apply(args=(str(scan_id), str(DEMO_ACCOUNT_ID))).get()
        run_execution_task.apply(args=(str(scan_id), str(DEMO_ACCOUNT_ID))).get()
        finalize_scan_task.apply(args=(str(scan_id), str(DEMO_ACCOUNT_ID))).get()

        with SessionLocal() as s:
            scan = ScanRepository(s).get(DEMO_ACCOUNT_ID, scan_id)
            jobs = JobRepository(s).list_for_scan(DEMO_ACCOUNT_ID, scan_id)
            gaps = GapRepository(s).list_for_scan(DEMO_ACCOUNT_ID, scan_id)

        # Whole-pipeline status, and per-stage progress readable from the scan.
        assert scan.status == "completed"
        assert set(scan.stats["stages"]) == {"monitor", "diagnosis", "execution"}
        assert scan.stats["stages"]["monitor"]["mentions"] > 0

        # One jobs row per stage, all succeeded.
        assert {j.type for j in jobs} == {"monitor", "diagnosis", "execution"}
        assert all(j.status == "succeeded" for j in jobs)

        # Diagnosis produced gaps (offline, via the mock-mode fixture site)...
        assert gaps, "diagnosis should produce gaps for the demo account"

        # ...and execution planned them. No generators are registered in this
        # distribution, so the stage reports what it could not build and the
        # CHAIN STILL COMPLETES — that is the property under test. A crash here
        # would fail the scan and abort the chain instead.
        execution = scan.stats["stages"]["execution"]
        assert execution["skipped_generation"] is True
        assert execution["backlog"], "planning must still produce a ranked backlog"
        assert execution["unsupported_fix_types"]
        assert "asset_id" not in execution

        # Nothing was persisted, because nothing was generated.
        with SessionLocal() as s:
            made = (
                s.query(AssetRow)
                .filter(
                    AssetRow.account_id == DEMO_ACCOUNT_ID,
                    AssetRow.created_at >= started,
                )
                .count()
            )
        assert made == 0, "no asset should be created by a run with no generators"
    finally:
        with SessionLocal() as s:
            AccountRepository(s).get_by_id(DEMO_ACCOUNT_ID).plan = original_plan
            s.commit()


def test_execution_skips_cleanly_when_there_are_no_gaps():
    if not _db_ready():
        pytest.skip("database unreachable — run docker compose up + db:migrate/seed")

    # A fresh scan has no gaps: that's a clean site, not a pipeline failure.
    scan_id = _new_scan(DEMO_ACCOUNT_ID)
    result = run_execution_task.apply(args=(str(scan_id), str(DEMO_ACCOUNT_ID))).get()

    assert result["skipped"] is True
    with SessionLocal() as s:
        scan = ScanRepository(s).get(DEMO_ACCOUNT_ID, scan_id)
        jobs = JobRepository(s).list_for_scan(DEMO_ACCOUNT_ID, scan_id)
    assert scan.status != "failed"
    assert [j.status for j in jobs] == ["succeeded"]


def test_a_failing_stage_marks_the_scan_failed_and_reraises():
    """The bookkeeping half: a raising stage records the failure everywhere and
    lets the exception out (which is what makes Celery abort the chain)."""
    if not _db_ready():
        pytest.skip("database unreachable — run docker compose up + db:migrate/seed")

    scan_id = _new_scan(DEMO_ACCOUNT_ID)

    def _boom() -> dict:
        raise RuntimeError("stage exploded")

    with pytest.raises(RuntimeError, match="stage exploded"):
        _stage("diagnosis", DEMO_ACCOUNT_ID, scan_id, _boom)

    with SessionLocal() as s:
        scan = ScanRepository(s).get(DEMO_ACCOUNT_ID, scan_id)
        jobs = JobRepository(s).list_for_scan(DEMO_ACCOUNT_ID, scan_id)

    # The scan carries the failure (so polling shows it), and the job records it.
    assert scan.status == "failed"
    assert "stage exploded" in scan.error
    assert [j.status for j in jobs] == ["failed"]
    assert "stage exploded" in jobs[0].error


def test_a_failing_stage_aborts_the_chain_downstream_never_runs(monkeypatch):
    """The abort half, through the REAL chain: when diagnosis blows up, execution
    and finalize must never run.

    Proof is the jobs table: `_stage` inserts a row the moment a stage starts, so
    the absence of an `execution` row means that stage never even began. Celery
    runs the chain inline here (task_always_eager) so no broker is needed.
    """
    if not _db_ready():
        pytest.skip("database unreachable — run docker compose up + db:migrate/seed")

    scan_id = _new_scan(DEMO_ACCOUNT_ID)

    def _boom(*_args, **_kwargs) -> dict:
        raise RuntimeError("diagnosis exploded")

    # Blow up the real diagnosis runner as the task calls it.
    monkeypatch.setattr("app.pipeline.tasks.run_diagnosis", _boom)

    previous_eager = celery_app.conf.task_always_eager
    previous_propagates = celery_app.conf.task_eager_propagates
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    try:
        # An eager chain re-raises when it reads the failed parent's result; the
        # DB state below is the assertion that matters either way.
        with suppress(RuntimeError):
            start_pipeline(scan_id, DEMO_ACCOUNT_ID)
    finally:
        celery_app.conf.task_always_eager = previous_eager
        celery_app.conf.task_eager_propagates = previous_propagates

    with SessionLocal() as s:
        scan = ScanRepository(s).get(DEMO_ACCOUNT_ID, scan_id)
        jobs = JobRepository(s).list_for_scan(DEMO_ACCOUNT_ID, scan_id)

    by_type = {j.type: j.status for j in jobs}
    assert by_type["monitor"] == "succeeded"  # ran before the failure
    assert by_type["diagnosis"] == "failed"
    # THE point: the chain aborted — execution never started, so it has no row.
    assert "execution" not in by_type

    # And finalize never ran either, so the scan is failed, not completed.
    assert scan.status == "failed"
    assert "diagnosis exploded" in scan.error
    assert "execution" not in scan.stats.get("stages", {})
