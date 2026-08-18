# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Integration test: the pipeline reads the seeded demo account via repositories.

Requires the local DB to be migrated and seeded (see services/pipeline/README).
Skips cleanly if the database is unreachable so unit runs don't hard-fail.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import OperationalError

from app.db.base import SessionLocal
from app.db.repositories import (
    AccountRepository,
    CompetitorRepository,
    PromptRepository,
)

DEMO_ACCOUNT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def session():
    try:
        sess = SessionLocal()
        sess.connection()  # force a real connection now
    except OperationalError:
        pytest.skip("database unreachable — run docker compose up + db:migrate/seed")
    try:
        yield sess
    finally:
        sess.close()


def test_reads_demo_account(session) -> None:
    account = AccountRepository(session).get_by_id(DEMO_ACCOUNT_ID)
    assert account is not None, "demo account missing — run db:seed"
    assert account.slug == "acme-analytics"
    assert account.brand_name == "Acme Analytics"


def test_reads_demo_competitors_and_prompts(session) -> None:
    competitors = CompetitorRepository(session).list_by_account(DEMO_ACCOUNT_ID)
    assert len(competitors) >= 3
    assert any(c.is_self for c in competitors)

    prompts = PromptRepository(session).list_by_account(
        DEMO_ACCOUNT_ID, active_only=True
    )
    assert len(prompts) >= 3
