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
    Boolean,
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

import app.modules.geo.models  # noqa: E402,F401  (FK targets: route_versions, corridor_stops)
from app.contracts.route_position import ROAD_POSITION_COMMENT
from app.db.base import Base

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
        Index(
            "ix_trips_direction_id",
            "direction_id",
            postgresql_where=text("direction_id IS NOT NULL"),
            sqlite_where=text("direction_id IS NOT NULL"),
        ),
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
    # ADR-0027 (0096): the driver direction this trip was made from; manual and legacy trips have none.
    direction_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("driver_directions.id", name="fk_trips_direction_id")
    )
    # ADR-0028 (0097, Q159): the part of the confirmed road the trip drives, metres from the road's start.
    route_start_m: Mapped[int | None] = mapped_column(Integer, comment=ROAD_POSITION_COMMENT)
    route_end_m: Mapped[int | None] = mapped_column(Integer, comment=ROAD_POSITION_COMMENT)
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


class TripCapacityClaim(Base):
    """ADR-0028 (0097, Q159): the road interval ``[from_m, to_m)`` a booking occupies on its trip, and the resources.

    One active claim per booking. Content is immutable; ``active`` goes true -> false once (release contract). The
    DB checks, under the trip row lock, that the active claims fit the trip at every point of the road. Phase 1:
    written next to ``booking_allocations`` (dual write, deferred parity trigger); the segment model still decides.
    """

    __tablename__ = "trip_capacity_claims"
    __table_args__ = (
        Index(
            "uq_trip_capacity_claims_booking_active",
            "booking_id",
            unique=True,
            postgresql_where=text("active"),
            sqlite_where=text("active"),
        ),
        Index(
            "ix_trip_capacity_claims_trip_active",
            "trip_id",
            "from_m",
            postgresql_where=text("active"),
            sqlite_where=text("active"),
        ),
        Index("ix_trip_capacity_claims_booking", "booking_id", "id"),
        Index("ix_trip_capacity_claims_trip", "trip_id"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    trip_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("trips.id", name="fk_trip_capacity_claims_trip_id"), nullable=False
    )
    # bookings.models imports this module, so the target resolves lazily by name (no ORM relationship, ADR-0001).
    booking_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bookings.id", name="fk_trip_capacity_claims_booking_id"), nullable=False
    )
    from_m: Mapped[int] = mapped_column(Integer, nullable=False)
    to_m: Mapped[int] = mapped_column(Integer, nullable=False)
    seats: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    baggage_ml: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cargo_weight_g: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cargo_volume_ml: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DriverDirection(Base):
    """ADR-0027 (0096): a driver's standing "where from -> where to" (Q150).

    Region + optional district on each end, the car and the capacity it offers. No time, stop, corridor or route is
    asked from the driver: ``corridor_id`` is what the server resolved, kept for matching. Trips are made from a
    direction by the system when the driver makes an offer (Q152).
    """

    __tablename__ = "driver_directions"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_driver_directions_public_id"),
        Index("ix_driver_directions_driver_status", "driver_user_id", "status", "id"),
        Index("ix_driver_directions_corridor", "corridor_id"),
        Index(
            "uq_driver_directions_live_ends",
            "driver_user_id",
            "origin_region_id",
            "origin_district_id",
            "destination_region_id",
            "destination_district_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text("status <> 'archived'"),
            sqlite_where=text("status <> 'archived'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    driver_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_driver_directions_driver_user_id"), nullable=False
    )
    vehicle_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vehicles.id", name="fk_driver_directions_vehicle_id"), nullable=False
    )
    corridor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("service_corridors.id", name="fk_driver_directions_corridor_id"), nullable=False
    )
    origin_region_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("regions.id", name="fk_driver_directions_origin_region_id"), nullable=False
    )
    origin_district_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("geo_districts.id", name="fk_driver_directions_origin_district_id")
    )
    destination_region_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("regions.id", name="fk_driver_directions_destination_region_id"), nullable=False
    )
    destination_district_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("geo_districts.id", name="fk_driver_directions_destination_district_id")
    )
    seat_capacity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    cargo_capacity_weight_g: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cargo_capacity_volume_ml: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'active'"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
