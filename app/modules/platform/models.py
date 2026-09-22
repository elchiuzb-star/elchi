"""ORM mapping for the platform tables created by migration 20260913_0031.

The migration is the source of truth (CHECKs, partial indexes, triggers). These
classes mirror columns, unique constraints and indexes so that the ORM drift
check in tests/pg stays empty, and stay SQLite-creatable for the legacy suite.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# BIGINT identity on PostgreSQL; plain INTEGER rowid alias on SQLite so the
# legacy in-memory suite can autoincrement.
BigIdentity = BigInteger().with_variant(Integer(), "sqlite")
JsonB = JSONB().with_variant(JSON(), "sqlite")


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("actor_user_id", "route", "idem_key", name="uq_idempotency_records_actor_route_key"),
        Index("ix_idempotency_records_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    actor_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    route: Mapped[str] = mapped_column(String(255), nullable=False)
    idem_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    response_status: Mapped[int | None] = mapped_column(SmallInteger)
    response_body: Mapped[Any | None] = mapped_column(JsonB)
    resource_type: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_outbox_events_event_id"),
        Index(
            "ix_outbox_events_pending",
            "next_attempt_at",
            postgresql_where=text("dispatched_at IS NULL AND dead_lettered_at IS NULL"),
            sqlite_where=text("dispatched_at IS NULL AND dead_lettered_at IS NULL"),
        ),
        Index("ix_outbox_events_aggregate", "aggregate_type", "aggregate_public_id"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[int | None] = mapped_column(BigInteger)
    aggregate_public_id: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonB, nullable=False)
    dedup_key: Mapped[str | None] = mapped_column(String(255))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ConsumerReceipt(Base):
    __tablename__ = "consumer_receipts"
    __table_args__ = (UniqueConstraint("consumer", "event_id", name="uq_consumer_receipts_consumer_event"),)

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    consumer: Mapped[str] = mapped_column(String(64), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PlatformEnvironment(Base):
    """Singleton DB-level environment marker (BR N1). See service.DB_ENVIRONMENT_* docs."""

    __tablename__ = "platform_environment"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    set_by: Mapped[str] = mapped_column(String(128), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PlatformEnvironmentHistory(Base):
    """Append-only marker history (migration 0042). A recorded production value forbids re-insert."""

    __tablename__ = "platform_environment_history"
    __table_args__ = (Index("ix_platform_environment_history_environment", "environment"),)

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    set_by: Mapped[str] = mapped_column(String(128), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
