# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""SQLAlchemy engine, session factory, and declarative base.

The engine is created lazily (no connection until first use), so importing this
module is cheap and side-effect-free.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime

from sqlalchemy import TIMESTAMP, create_engine, func
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    """created_at/updated_at present on every table except append-only logs."""

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


_engine = create_engine(get_settings().database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, class_=Session)


def get_engine():
    return _engine


def session_scope() -> Generator[Session, None, None]:
    """Yield a session and ensure it is closed."""
    with SessionLocal() as session:
        yield session
