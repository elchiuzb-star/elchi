"""ORM mapping for tracking tables created by migration 20260916_0058 (A6).

The migration is the source of truth: CHECKs, the DEFAULT partition, daily partitions (SECURITY DEFINER functions),
guard triggers (``tracking_session_superseded``, ``tracking_session_closed``, ``append_only_violation``) live only in
the database. Columns, unique constraints, indexes and foreign keys are mirrored here (drift test in tests/pg/tracking).
Geometry columns are opaque: write with ``ST_SetSRID(ST_MakePoint(lng, lat), 4326)``, read with ``ST_Y``/``ST_X``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CHAR,
    JSON,
    BigInteger,
    Boolean,
    Date,
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
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

import app.modules.bookings.models  # noqa: F401  (FK target: bookings)
import app.modules.trips.models  # noqa: F401  (FK target: trips)
from app.db.base import Base
from app.modules.geo.models import Geometry

BigIdentity = BigInteger().with_variant(Integer(), "sqlite")
TextArray = ARRAY(Text()).with_variant(JSON(), "sqlite")

TRACKING_TABLES: tuple[str, ...] = (
    "tracking_sessions",
    "tracking_points",
    "tracking_point_receipts",
    "tracking_track_simplified",
    "tracking_grants",
    # wave 3.1 (M1, migration 0063)
    "tracking_evidence_holds",
    "tracking_evidence_points",
)
ACTIVE_SESSION_INDEX = "uq_tracking_sessions_trip_active"


class TrackingSession(Base):
    __tablename__ = "tracking_sessions"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_tracking_sessions_public_id"),
        Index(
            ACTIVE_SESSION_INDEX,
            "trip_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        Index("ix_tracking_sessions_trip_started", "trip_id", "started_at", "id"),
        Index("ix_tracking_sessions_driver_started", "driver_user_id", "started_at"),
        Index(
            "ix_tracking_sessions_active_last_captured",
            "last_captured_at",
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    trip_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("trips.id", name="fk_tracking_sessions_trip_id"), nullable=False
    )
    driver_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_tracking_sessions_driver_user_id"), nullable=False
    )
    device_id: Mapped[str] = mapped_column(String(128), nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    app_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'active'"))
    last_seq: Mapped[int | None] = mapped_column(BigInteger)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_point: Mapped[str | None] = mapped_column(Geometry("Point"))
    last_accuracy_m: Mapped[int | None] = mapped_column(Integer)
    candidate_captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    candidate_point: Mapped[str | None] = mapped_column(Geometry("Point"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TrackingPoint(Base):
    """Partitioned by RANGE (captured_date) in PostgreSQL; history, never the live marker by itself."""

    __tablename__ = "tracking_points"
    __table_args__ = (
        Index("ix_tracking_points_session_captured", "session_id", "captured_at"),
        {"postgresql_partition_by": "RANGE (captured_date)"},
    )

    captured_date: Mapped[date] = mapped_column(Date, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tracking_sessions.id", name="fk_tracking_points_session_id"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    point: Mapped[str] = mapped_column(Geometry("Point"), nullable=False)
    accuracy_m: Mapped[int] = mapped_column(Integer, nullable=False)
    speed_mps: Mapped[int | None] = mapped_column(Integer)
    heading_deg: Mapped[int | None] = mapped_column(SmallInteger)
    battery_pct: Mapped[int | None] = mapped_column(SmallInteger)
    is_mock: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    quality_flags: Mapped[list[str]] = mapped_column(TextArray, nullable=False, server_default=text("'{}'"))


class TrackingPointReceipt(Base):
    """Append-only dedup receipt per ``(session, seq)`` (AC28); kept 8 days (``POINT_RECEIPT_RETENTION``)."""

    __tablename__ = "tracking_point_receipts"
    __table_args__ = (Index("ix_tracking_point_receipts_received_at", "received_at"),)

    session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tracking_sessions.id", name="fk_tracking_point_receipts_session_id"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    captured_date: Mapped[date] = mapped_column(Date, nullable=False)
    payload_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TrackingTrackSimplified(Base):
    __tablename__ = "tracking_track_simplified"
    __table_args__ = (
        UniqueConstraint("trip_id", name="uq_tracking_track_simplified_trip_id"),
        Index("ix_tracking_track_simplified_generated_at", "generated_at"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    trip_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("trips.id", name="fk_tracking_track_simplified_trip_id"), nullable=False
    )
    geometry: Mapped[str] = mapped_column(Geometry("LineString"), nullable=False)
    point_count: Mapped[int] = mapped_column(Integer, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TrackingGrant(Base):
    """K5 recipient link: only the SHA-256 of the token is stored (ADR-0018)."""

    __tablename__ = "tracking_grants"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_tracking_grants_public_id"),
        UniqueConstraint("token_hash", name="uq_tracking_grants_token_hash"),
        Index("ix_tracking_grants_booking_id", "booking_id"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    booking_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bookings.id", name="fk_tracking_grants_booking_id"), nullable=False
    )
    grantee_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_tracking_grants_grantee_user_id")
    )
    token_hash: Mapped[str | None] = mapped_column(CHAR(64))
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_tracking_grants_created_by_user_id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TrackingEvidenceHold(Base):
    """M1: while a hold is open, the raw points of ``trip_id`` are copied out of the expiring daily partitions.

    ``source_type``/``source_id`` name the business row that asked for the hold (a dispute) without a foreign key
    into another module's tables (AGENTS §4). Released holds are purged with their points 30 days later
    (``contracts.tracking.EVIDENCE_RETENTION_AFTER_RELEASE``).
    """

    __tablename__ = "tracking_evidence_holds"
    __table_args__ = (
        UniqueConstraint("trip_id", "source_type", "source_id", name="uq_tracking_evidence_holds_source"),
        Index("ix_tracking_evidence_holds_active", "trip_id", postgresql_where=text("released_at IS NULL")),
        Index("ix_tracking_evidence_holds_released", "released_at", postgresql_where=text("released_at IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    trip_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("trips.id", name="fk_tracking_evidence_holds_trip_id"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TrackingEvidencePoint(Base):
    """A copy of one raw point of a held trip, kept outside the daily partitions. Append-only (UPDATE refused)."""

    __tablename__ = "tracking_evidence_points"
    __table_args__ = (Index("ix_tracking_evidence_points_trip", "trip_id", "captured_at"),)

    session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tracking_sessions.id", name="fk_tracking_evidence_points_session_id"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    trip_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("trips.id", name="fk_tracking_evidence_points_trip_id"), nullable=False
    )
    captured_date: Mapped[date] = mapped_column(Date, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    point: Mapped[str] = mapped_column(Geometry("Point"), nullable=False)
    accuracy_m: Mapped[int] = mapped_column(Integer, nullable=False)
    speed_mps: Mapped[int | None] = mapped_column(Integer)
    heading_deg: Mapped[int | None] = mapped_column(SmallInteger)
    battery_pct: Mapped[int | None] = mapped_column(SmallInteger)
    is_mock: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    quality_flags: Mapped[list[str]] = mapped_column(TextArray, nullable=False, server_default=text("'{}'"))
    copied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
