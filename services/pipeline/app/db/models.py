"""SQLAlchemy models — a hand-written MIRROR of db/migrations/*.sql.

The SQL is the single source of truth. Enum columns reference the existing
Postgres enum types (create_type=False) — they are never created from here.
Lifecycle states are enums; open taxonomies (engine, gap_type, *_type) are Text.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    TIMESTAMP as SA_TIMESTAMP,
)
from sqlalchemy import (
    BigInteger,
    Boolean,
    Enum,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    Text,
)
from sqlalchemy import (
    func as sa_func,
)
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# ── Enum types (mirror the Postgres ENUMs; do not create from here) ──────
user_role = Enum(
    "owner", "admin", "member", name="user_role", create_type=False, native_enum=True
)
scan_status = Enum(
    "pending",
    "running",
    "completed",
    "failed",
    "canceled",
    name="scan_status",
    create_type=False,
    native_enum=True,
)
job_status = Enum(
    "queued",
    "running",
    "succeeded",
    "failed",
    "canceled",
    name="job_status",
    create_type=False,
    native_enum=True,
)
gap_status = Enum(
    "open",
    "planned",
    "in_progress",
    "resolved",
    "dismissed",
    name="gap_status",
    create_type=False,
    native_enum=True,
)
asset_status = Enum(
    "draft",
    "generated",
    "validated",
    "published",
    "rejected",
    name="asset_status",
    create_type=False,
    native_enum=True,
)
asset_validation_state = Enum(
    "pending",
    "passed",
    "failed",
    name="asset_validation_state",
    create_type=False,
    native_enum=True,
)
verification_verdict = Enum(
    "improved",
    "no_change",
    "regressed",
    "inconclusive",
    name="verification_verdict",
    create_type=False,
    native_enum=True,
)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=sa_func.gen_random_uuid()
    )


def _account_fk(ondelete: str = "CASCADE") -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete=ondelete),
        nullable=False,
    )


class Account(TimestampMixin, Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str | None] = mapped_column(Text)
    brand_name: Mapped[str | None] = mapped_column(Text)
    brand_aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    plan: Mapped[str] = mapped_column(Text, nullable=False, server_default="free")
    subscription_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="trialing"
    )
    trial_ends_at: Mapped[datetime | None] = mapped_column(SA_TIMESTAMP(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(
        SA_TIMESTAMP(timezone=True)
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(Text)
    stripe_subscription_id: Mapped[str | None] = mapped_column(Text)
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    account_id: Mapped[uuid.UUID] = _account_fk()
    email: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(
        user_role, nullable=False, server_default="member"
    )
    password_hash: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    last_login_at: Mapped[datetime | None] = mapped_column(SA_TIMESTAMP(timezone=True))


class Competitor(TimestampMixin, Base):
    __tablename__ = "competitors"

    id: Mapped[uuid.UUID] = _uuid_pk()
    account_id: Mapped[uuid.UUID] = _account_fk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str | None] = mapped_column(Text)
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    is_self: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )


class Prompt(TimestampMixin, Base):
    __tablename__ = "prompts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    account_id: Mapped[uuid.UUID] = _account_fk()
    text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text)
    prompt_group: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class Scan(TimestampMixin, Base):
    __tablename__ = "scans"

    id: Mapped[uuid.UUID] = _uuid_pk()
    account_id: Mapped[uuid.UUID] = _account_fk()
    status: Mapped[str] = mapped_column(
        scan_status, nullable=False, server_default="pending"
    )
    engine_set: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="[]")
    triggered_by: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(SA_TIMESTAMP(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(SA_TIMESTAMP(timezone=True))
    stats: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    error: Mapped[str | None] = mapped_column(Text)


class Mention(TimestampMixin, Base):
    __tablename__ = "mentions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[uuid.UUID] = _account_fk()
    scan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scans.id", ondelete="CASCADE"), nullable=False
    )
    prompt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False
    )
    engine: Mapped[str] = mapped_column(Text, nullable=False)
    run: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    brand: Mapped[str | None] = mapped_column(Text)
    competitor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("competitors.id", ondelete="SET NULL")
    )
    mentioned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    position: Mapped[int | None] = mapped_column(Integer)
    sentiment: Mapped[str | None] = mapped_column(Text)
    sentiment_score: Mapped[Decimal | None] = mapped_column(Numeric)
    cited_urls: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="[]")
    raw_response_ref: Mapped[str | None] = mapped_column(Text)


class ShareOfVoice(TimestampMixin, Base):
    __tablename__ = "share_of_voice"

    id: Mapped[uuid.UUID] = _uuid_pk()
    account_id: Mapped[uuid.UUID] = _account_fk()
    scan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scans.id", ondelete="CASCADE"), nullable=False
    )
    brand: Mapped[str] = mapped_column(Text, nullable=False)
    competitor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("competitors.id", ondelete="SET NULL")
    )
    is_self: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    engine: Mapped[str] = mapped_column(Text, nullable=False, server_default="all")
    mention_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    mention_rate: Mapped[Decimal | None] = mapped_column(Numeric)
    avg_position: Mapped[Decimal | None] = mapped_column(Numeric)
    sov_pct: Mapped[Decimal | None] = mapped_column(Numeric)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )


class Gap(TimestampMixin, Base):
    __tablename__ = "gaps"

    id: Mapped[uuid.UUID] = _uuid_pk()
    account_id: Mapped[uuid.UUID] = _account_fk()
    scan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scans.id", ondelete="SET NULL")
    )
    prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prompts.id", ondelete="SET NULL")
    )
    gap_type: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    rank_score: Mapped[Decimal | None] = mapped_column(Numeric)
    status: Mapped[str] = mapped_column(
        gap_status, nullable=False, server_default="open"
    )


class Asset(TimestampMixin, Base):
    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = _uuid_pk()
    account_id: Mapped[uuid.UUID] = _account_fk()
    gap_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gaps.id", ondelete="SET NULL")
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    content_ref: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )
    target_prompt_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default="{}"
    )
    status: Mapped[str] = mapped_column(
        asset_status, nullable=False, server_default="draft"
    )
    validation_state: Mapped[str] = mapped_column(
        asset_validation_state, nullable=False, server_default="pending"
    )


class Verification(TimestampMixin, Base):
    __tablename__ = "verifications"

    id: Mapped[uuid.UUID] = _uuid_pk()
    account_id: Mapped[uuid.UUID] = _account_fk()
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    scan_before_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scans.id", ondelete="SET NULL")
    )
    scan_after_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scans.id", ondelete="SET NULL")
    )
    before_metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    after_metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric)
    verdict: Mapped[str] = mapped_column(
        verification_verdict, nullable=False, server_default="inconclusive"
    )


class VerifiedFact(TimestampMixin, Base):
    __tablename__ = "verified_facts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    account_id: Mapped[uuid.UUID] = _account_fk()
    fact_type: Mapped[str] = mapped_column(Text, nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    source: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    effective_from: Mapped[datetime | None] = mapped_column(SA_TIMESTAMP(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(SA_TIMESTAMP(timezone=True))


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    account_id: Mapped[uuid.UUID] = _account_fk()
    scan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scans.id", ondelete="SET NULL")
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        job_status, nullable=False, server_default="queued"
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    external_id: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(SA_TIMESTAMP(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(SA_TIMESTAMP(timezone=True))


class AuditLog(Base):
    """Append-only: created_at only, no updated_at."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL")
    )
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[str | None] = mapped_column(Text)
    resource_id: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )
    ip: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(
        SA_TIMESTAMP(timezone=True), server_default=sa_func.now(), nullable=False
    )


class LlmCostLog(Base):
    """Append-only: created_at only, no updated_at."""

    __tablename__ = "llm_cost_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[uuid.UUID] = _account_fk()
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL")
    )
    scan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scans.id", ondelete="SET NULL")
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    operation: Mapped[str | None] = mapped_column(Text)
    prompt_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    completion_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    total_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, server_default="0"
    )
    mock: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # Complete-ledger flags (see 0004): cached calls made no provider request
    # (cost 0); status is 'ok' or 'error' (a call that raised, logged with zero
    # usage). "actual spend" = rows with cached=false and status='ok'.
    cached: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="ok")
    created_at: Mapped[datetime] = mapped_column(
        SA_TIMESTAMP(timezone=True), server_default=sa_func.now(), nullable=False
    )


class CmsCredential(TimestampMixin, Base):
    """Envelope-encrypted CMS credentials; plaintext never stored or returned."""

    __tablename__ = "cms_credentials"

    id: Mapped[uuid.UUID] = _uuid_pk()
    account_id: Mapped[uuid.UUID] = _account_fk()
    cms_type: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    key_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    encrypted_dek: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    last_used_at: Mapped[datetime | None] = mapped_column(SA_TIMESTAMP(timezone=True))
