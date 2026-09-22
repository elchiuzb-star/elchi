"""ORM mapping for trips tables created by migrations 20260913_0037 and 20260913_0038.

Migrations are the source of truth: CHECK constraints, the driver/vehicle overlap
EXCLUDE constraints (AC13) and the used <= capacity CHECKs (AC10/AC11) live only
in the database. Columns, unique constraints and indexes are mirrored here.

Cross-module foreign keys (``route_versions``, ``corridor_stops``) are declared
without ORM relationships (ADR-0001); the geo models are imported so they resolve.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
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
from sqlalchemy.dialects.postgresql import ARRAY, TSTZRANGE
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
import app.modules.geo.models  # noqa: E402,F401  (FK targets: route_versions, corridor_stops)

BigIdentity = BigInteger().with_variant(Integer(), "sqlite")
TextArray = ARRAY(Text()).with_variant(JSON(), "sqlite")
TimeRange = TSTZRANGE().with_variant(Text(), "sqlite")


class Vehicle(Base):
    __tablename__ = "vehicles"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_vehicles_public_id"),
        UniqueConstraint("plate_normalized", name="uq_vehicles_plate_normalized"),
        Index("ix_vehicles_driver_user_id", "driver_user_id"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    driver_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_vehicles_driver_user_id"), nullable=False
    )
    plate_number: Mapped[str] = mapped_column(String(32), nullable=False)
    plate_normalized: Mapped[str] = mapped_column(String(32), nullable=False)
    make_model: Mapped[str] = mapped_column(String(120), nullable=False)
    color: Mapped[str] = mapped_column(String(64), nullable=False)
    seat_capacity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    baggage_capacity_ml: Mapped[int | None] = mapped_column(Integer)
    cargo_max_weight_g: Mapped[int | None] = mapped_column(Integer)
    cargo_max_volume_ml: Mapped[int | None] = mapped_column(Integer)
    document_file_ids: Mapped[list[str]] = mapped_column(TextArray, nullable=False, server_default=text("'{}'"))
    verification_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'pending'"))
    verification_reason: Mapped[str | None] = mapped_column(Text)
    verified_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", name="fk_vehicles_verified_by"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Trip(Base):
    __tablename__ = "trips"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_trips_public_id"),
        Index("ix_trips_driver_user_id_planned_start_at", "driver_user_id", "planned_start_at", "id"),
        Index("ix_trips_vehicle_id", "vehicle_id"),
        Index("ix_trips_status_planned_start_at", "status", "planned_start_at"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    driver_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_trips_driver_user_id"), nullable=False
    )
    vehicle_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vehicles.id", name="fk_trips_vehicle_id"), nullable=False
    )
    route_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("route_versions.id", name="fk_trips_route_version_id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'planned'"))
    planned_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    planned_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    blocked_period: Mapped[object] = mapped_column(TimeRange, nullable=False)
    booking_cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("'Asia/Tashkent'"))
    seat_capacity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    baggage_capacity_ml: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cargo_capacity_weight_g: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cargo_capacity_volume_ml: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_detour_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    max_detour_m: Mapped[int] = mapped_column(Integer, nullable=False)
    detour_used_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # Seconds (migration 0045, AGENTS §6 "Detour"); detour_used_minutes is legacy and no longer written.
    detour_used_s: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    detour_used_m: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    pickup_wait_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("10"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    interrupted_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TripStopOccurrence(Base):
    __tablename__ = "trip_stop_occurrences"
    __table_args__ = (UniqueConstraint("trip_id", "seq", name="uq_trip_stop_occurrences_trip_seq"),)

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    trip_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("trips.id", name="fk_trip_stop_occurrences_trip_id", ondelete="CASCADE"),
        nullable=False,
    )
    seq: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    stop_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("corridor_stops.id", name="fk_trip_stop_occurrences_stop_id"), nullable=False
    )
    route_version_stop_seq: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    planned_arrival_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dwell_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    eta_arrival_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TripSegmentResource(Base):
    __tablename__ = "trip_segment_resources"
    __table_args__ = (UniqueConstraint("trip_id", "from_seq", name="uq_trip_segment_resources_trip_from_seq"),)

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    trip_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("trips.id", name="fk_trip_segment_resources_trip_id", ondelete="CASCADE"),
        nullable=False,
    )
    from_seq: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    to_seq: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    seat_capacity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    seats_used: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    baggage_capacity_ml: Mapped[int] = mapped_column(Integer, nullable=False)
    baggage_used_ml: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cargo_capacity_weight_g: Mapped[int] = mapped_column(Integer, nullable=False)
    cargo_used_weight_g: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cargo_capacity_volume_ml: Mapped[int] = mapped_column(Integer, nullable=False)
    cargo_used_volume_ml: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
