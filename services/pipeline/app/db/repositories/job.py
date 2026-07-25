"""Tenant-scoped data access for pipeline job rows (per-stage status/error)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Job


class JobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        account_id: uuid.UUID | str,
        scan_id: uuid.UUID | str | None,
        type: str,
        payload: dict[str, Any] | None = None,
        external_id: str | None = None,
    ) -> Job:
        row = Job(
            account_id=_as_uuid(account_id),
            scan_id=_as_uuid(scan_id),
            type=type,
            status="queued",
            payload=payload or {},
            external_id=external_id,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def mark_running(self, job_id: uuid.UUID) -> None:
        job = self.session.get(Job, job_id)
        if job is not None:
            job.status = "running"
            job.attempts = (job.attempts or 0) + 1
            job.started_at = datetime.now(UTC)
            self.session.flush()

    def mark_succeeded(self, job_id: uuid.UUID, result: dict[str, Any]) -> None:
        job = self.session.get(Job, job_id)
        if job is not None:
            job.status = "succeeded"
            job.result = result
            job.finished_at = datetime.now(UTC)
            self.session.flush()

    def mark_failed(self, job_id: uuid.UUID, error: str) -> None:
        job = self.session.get(Job, job_id)
        if job is not None:
            job.status = "failed"
            job.error = error[:2000]
            job.finished_at = datetime.now(UTC)
            self.session.flush()

    def list_for_scan(
        self, account_id: uuid.UUID | str, scan_id: uuid.UUID | str
    ) -> list[Job]:
        return list(
            self.session.scalars(
                select(Job)
                .where(
                    Job.account_id == _as_uuid(account_id),
                    Job.scan_id == _as_uuid(scan_id),
                )
                .order_by(Job.created_at)
            ).all()
        )


def _as_uuid(value: uuid.UUID | str | None) -> uuid.UUID | None:
    if value is None:
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)
