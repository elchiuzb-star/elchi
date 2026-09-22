"""ORM models for geo tables (migrations 20260913_0033, _0034, _0035).

The migrations are the source of truth (CHECKs, triggers, expression GiST indexes).
These models mirror columns, unique constraints, FKs and plain indexes so the
autogenerate drift gate stays empty, and they are dialect-safe so the SQLite unit
suite's ``Base.metadata.create_all`` keeps working when this module is imported.

Geometry columns are opaque here: write them with ``ST_GeomFromEWKT`` and read
coordinates with ``ST_X``/``ST_Y`` in the repository. Metre distances are always
computed on ``::geography``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator, UserDefinedType

import app.models  # noqa: F401  - registers legacy users/cities/districts, targets of geo FKs
from app.db.base import Base

BigId =BigInteger().with_variant(Integer(), "sqlite")
JsonDoc = JSONB().with_variant(JSON(), "sqlite")


class _PgGeometry(UserDefinedType):
    cache_ok = True

    def __init__(self, geometry_type: str, srid: int = 4326) -> None:
        self.geometry_type = geometry_type
        self.srid = srid

    def get_col_spec(self, **_kw: Any) -> str:
        return f"geometry({self.geometry_type},{self.srid})"


class Geometry(TypeDecorator):
    """``geometry(<type>,4326)`` on PostgreSQL; plain TEXT elsewhere (unit-test DDL only)."""

    impl = Text
    cache_ok = True

    def __init__(self, geometry_type: str, srid: int = 4326) -> None:
        super().__init__()
        self.geometry_type = geometry_type
        self.srid = srid

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(_PgGeometry(self.geometry_type, self.srid))
        return dialect.type_descriptor(Text())


def _pk() -> Mapped[int]:
    return mapped_column(BigId, Identity(always=True), primary_key=True)


def _ts() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# --- feature flags (0033) ----------------------------------------------------------


class FeatureFlagValue(Base):
    __tablename__ = "feature_flag_values"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_feature_flag_values_public_id"),
        UniqueConstraint("flag_key", "scope_type", "scope_ref", name="uq_feature_flag_values_key_scope"),
    )

    id: Mapped[int] = _pk()
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    flag_key: Mapped[str] = mapped_column(Text, nullable=False)
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_ref: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    approval_reference: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id", name="fk_feature_flag_values_updated_by"), nullable=False)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class FeatureFlagChange(Base):
    """Append-only; rows are written only by the DB trigger on ``feature_flag_values``."""

    __tablename__ = "feature_flag_changes"
    __table_args__ = (
        UniqueConstraint("flag_value_id", "value_version", name="uq_feature_flag_changes_value_version"),
        Index("ix_feature_flag_changes_key_changed", "flag_key", "changed_at", "id"),
    )

    id: Mapped[int] = _pk()
    flag_value_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("feature_flag_values.id", name="fk_feature_flag_changes_flag_value"), nullable=False
    )
    flag_key: Mapped[str] = mapped_column(Text, nullable=False)
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_ref: Mapped[str] = mapped_column(Text, nullable=False)
    value_version: Mapped[int] = mapped_column(Integer, nullable=False)
    old_enabled: Mapped[bool | None] = mapped_column(Boolean)
    new_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", name="fk_feature_flag_changes_actor"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    approval_reference: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = _ts()


# --- catalogue (0034) ---------------------------------------------------------------


class Region(Base):
    __tablename__ = "regions"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_regions_public_id"),
        UniqueConstraint("code", name="uq_regions_code"),
        Index("ix_regions_boundary_gist", "boundary", postgresql_using="gist").ddl_if(dialect="postgresql"),
    )

    id: Mapped[int] = _pk()
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name_uz: Mapped[str] = mapped_column(Text, nullable=False)
    name_ru: Mapped[str | None] = mapped_column(Text)
    boundary: Mapped[Any | None] = mapped_column(Geometry("MultiPolygon"), nullable=True)
    #: Where a map opens for this region when no district centre applies (0080) - Tashkent city, where the
    #: city itself is the direction unit. Advisory, exactly like `GeoDistrict.center_lat`.
    center_lat: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 7),
        comment=(
            "Advisory map viewport hint (wave 17): where a picker opens for this region when no district "
            "centre applies. Never a matching, capacity or pricing input (spec section 2, Q88)."
        ),
    )
    center_lng: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), comment="See center_lat.")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    #: Wave 10: the direction picker asks for a district in this region. False for Tashkent city, where the
    #: city itself is the unit (user decision 17.09.2026). Data, so an operator can correct it per region.
    requires_district: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
        comment=(
            "Direction selection asks for a district in this region (user decision 17.09.2026). False for "
            "Tashkent city, where the city itself is the unit. Data, not code: operators may change it."
        ),
    )
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class GeoDistrict(Base):
    __tablename__ = "geo_districts"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_geo_districts_public_id"),
        UniqueConstraint("legacy_district_id", name="uq_geo_districts_legacy_district_id"),
        Index("ix_geo_districts_region_lower_name_uz", "region_id", text("lower(name_uz)"), unique=True),
        Index("ix_geo_districts_boundary_gist", "boundary", postgresql_using="gist").ddl_if(dialect="postgresql"),
    )

    id: Mapped[int] = _pk()
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    region_id: Mapped[int] = mapped_column(BigId, ForeignKey("regions.id", name="fk_geo_districts_region"), nullable=False)
    name_uz: Mapped[str] = mapped_column(Text, nullable=False)
    name_ru: Mapped[str | None] = mapped_column(Text)
    legacy_district_id: Mapped[int | None] = mapped_column(
        ForeignKey("districts.id", name="fk_geo_districts_legacy_district")
    )
    boundary: Mapped[Any | None] = mapped_column(Geometry("MultiPolygon"), nullable=True)
    #: Where a map should open when this district is chosen (0079).
    #:
    #: Advisory only. The specification rejects deciding a route by district (§2), and Q88 projects a marked
    #: point onto a confirmed route instead - so nothing in matching, capacity or pricing may read these. They
    #: exist because the alternative is opening every picker over Tashkent and making a person in Urgut drag
    #: the map across the country.
    center_lat: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 7),
        comment=(
            "Advisory map viewport hint (wave 17): where a picker opens when this district is chosen. Never a "
            "matching, capacity or pricing input - routes are decided by projection onto a confirmed route (Q88)."
        ),
    )
    center_lng: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), comment="See center_lat.")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class Settlement(Base):
    __tablename__ = "settlements"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_settlements_public_id"),
        Index("ix_settlements_point_gist", "point", postgresql_using="gist").ddl_if(dialect="postgresql"),
    )

    id: Mapped[int] = _pk()
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    district_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("geo_districts.id", name="fk_settlements_district"), nullable=False
    )
    name_uz: Mapped[str] = mapped_column(Text, nullable=False)
    name_ru: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    point: Mapped[Any] = mapped_column(Geometry("Point"), nullable=False)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class LegacyCityMapping(Base):
    __tablename__ = "legacy_city_mappings"
    __table_args__ = (UniqueConstraint("legacy_city_id", name="uq_legacy_city_mappings_legacy_city_id"),)

    id: Mapped[int] = _pk()
    legacy_city_id: Mapped[int] = mapped_column(
        ForeignKey("cities.id", name="fk_legacy_city_mappings_city"), nullable=False
    )
    region_id: Mapped[int | None] = mapped_column(BigId, ForeignKey("regions.id", name="fk_legacy_city_mappings_region"))
    settlement_id: Mapped[int | None] = mapped_column(
        BigId, ForeignKey("settlements.id", name="fk_legacy_city_mappings_settlement")
    )
    mapping_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'unverified'"))
    note: Mapped[str | None] = mapped_column(Text)
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", name="fk_legacy_city_mappings_verified_by"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class ServiceCorridor(Base):
    __tablename__ = "service_corridors"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_service_corridors_public_id"),
        Index("ix_service_corridors_lower_name", text("lower(name)"), unique=True),
    )

    id: Mapped[int] = _pk()
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    origin_region_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("regions.id", name="fk_service_corridors_origin_region"), nullable=False
    )
    destination_region_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("regions.id", name="fk_service_corridors_destination_region"), nullable=False
    )
    rollout_state: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    #: Q88: how far from the confirmed route a marked map point may sit on this corridor (metres). Operator
    #: configuration, not an application constant: a dense city and a long highway want different numbers.
    max_point_offset_m: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("3000"),
        comment=(
            "Q88: how far from the confirmed route a marked map point may sit on this corridor, in metres. "
            "Operator configuration - a dense city and a long highway do not want the same number."
        ),
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", name="fk_service_corridors_created_by"), nullable=False)
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id", name="fk_service_corridors_updated_by"), nullable=False)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class CorridorConfigVersion(Base):
    """Immutable (DB trigger)."""

    __tablename__ = "corridor_config_versions"
    __table_args__ = (UniqueConstraint("corridor_id", "revision", name="uq_corridor_config_versions_revision"),)

    id: Mapped[int] = _pk()
    corridor_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("service_corridors.id", name="fk_corridor_config_versions_corridor"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    search_radius_m: Mapped[int] = mapped_column(Integer, nullable=False)
    default_max_detour_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    default_max_detour_m: Mapped[int] = mapped_column(Integer, nullable=False)
    ranking_weights: Mapped[dict[str, Any]] = mapped_column(JsonDoc, nullable=False, server_default=text("'{}'"))
    price_reference: Mapped[dict[str, Any]] = mapped_column(JsonDoc, nullable=False, server_default=text("'{}'"))
    effective_from: Mapped[datetime] = _ts()
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", name="fk_corridor_config_versions_created_by"), nullable=False
    )
    created_at: Mapped[datetime] = _ts()


class CorridorStop(Base):
    __tablename__ = "corridor_stops"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_corridor_stops_public_id"),
        Index("ix_corridor_stops_corridor_lower_name_uz", "corridor_id", text("lower(name_uz)"), unique=True),
        Index("ix_corridor_stops_point_gist", "point", postgresql_using="gist").ddl_if(dialect="postgresql"),
        Index(
            "ix_corridor_stops_geography_gist", text("(point::geography)"), postgresql_using="gist"
        ).ddl_if(dialect="postgresql"),
        Index("ix_corridor_stops_district", "geo_district_id"),
    )

    id: Mapped[int] = _pk()
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    corridor_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("service_corridors.id", name="fk_corridor_stops_corridor"), nullable=False
    )
    geo_district_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("geo_districts.id", name="fk_corridor_stops_district"), nullable=False
    )
    name_uz: Mapped[str] = mapped_column(Text, nullable=False)
    name_ru: Mapped[str | None] = mapped_column(Text)
    point: Mapped[Any] = mapped_column(Geometry("Point"), nullable=False)
    meeting_note: Mapped[str | None] = mapped_column(Text)
    meeting_photo_file_id: Mapped[str | None] = mapped_column(Text)  # 0043, decision 27
    sequence_hint: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", name="fk_corridor_stops_verified_by"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


# --- route versions (0035) ----------------------------------------------------------


class RouteVersion(Base):
    """Draft -> confirmed once; confirmed rows immutable (DB trigger)."""

    __tablename__ = "route_versions"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_route_versions_public_id"),
        Index("ix_route_versions_geometry_gist", "geometry", postgresql_using="gist").ddl_if(dialect="postgresql"),
        Index(
            "ix_route_versions_geography_gist", text("(geometry::geography)"), postgresql_using="gist"
        ).ddl_if(dialect="postgresql"),
        Index("ix_route_versions_corridor_status", "corridor_id", "status"),
    )

    id: Mapped[int] = _pk()
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    corridor_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("service_corridors.id", name="fk_route_versions_corridor"), nullable=False
    )
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", name="fk_route_versions_created_by"), nullable=False
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_version: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    geometry: Mapped[Any] = mapped_column(Geometry("LineString"), nullable=False)
    distance_m: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_s: Mapped[int] = mapped_column(Integer, nullable=False)
    is_estimate: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class RouteVersionStop(Base):
    __tablename__ = "route_version_stops"
    __table_args__ = (
        UniqueConstraint("route_version_id", "seq", name="uq_route_version_stops_seq"),
        Index("ix_route_version_stops_stop", "stop_id"),
    )

    id: Mapped[int] = _pk()
    route_version_id: Mapped[int] = mapped_column(
        BigId,
        ForeignKey("route_versions.id", name="fk_route_version_stops_route_version", ondelete="CASCADE"),
        nullable=False,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    stop_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("corridor_stops.id", name="fk_route_version_stops_stop"), nullable=False
    )
    cumulative_distance_m: Mapped[int] = mapped_column(Integer, nullable=False)
    cumulative_duration_s: Mapped[int] = mapped_column(Integer, nullable=False)
    line_fraction: Mapped[Decimal] = mapped_column(Numeric(8, 7), nullable=False)


class RoutingCacheEntry(Base):
    __tablename__ = "routing_cache"
    __table_args__ = (
        UniqueConstraint("provider", "request_hash", name="uq_routing_cache_provider_request"),
        Index("ix_routing_cache_expires_at", "expires_at"),
    )

    id: Mapped[int] = _pk()
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    response: Mapped[dict[str, Any]] = mapped_column(JsonDoc, nullable=False)
    created_at: Mapped[datetime] = _ts()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


GEO_TABLES: tuple[str, ...] = (
    "feature_flag_values",
    "feature_flag_changes",
    "regions",
    "geo_districts",
    "settlements",
    "legacy_city_mappings",
    "service_corridors",
    "corridor_config_versions",
    "corridor_stops",
    "route_versions",
    "route_version_stops",
    "routing_cache",
)


# --- stop evidence guards + price bands (0046) --------------------------------------------


class CorridorPriceBand(Base):
    """Q42 floor/ceiling per corridor and service type, corridor-wide or per segment. Versioned;
    history rows are appended by a DB trigger; rows are never deleted (deactivate instead).

    Q90: a band is **advice** unless ``enforced`` - ELCHI's price is the one the two sides agree on, so an
    ordinary band warns and ranks rather than refusing an offer."""

    __tablename__ = "corridor_price_bands"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_corridor_price_bands_public_id"),
        Index(
            "ix_corridor_price_bands_corridor_scope",
            "corridor_id",
            "service_type",
            unique=True,
            postgresql_where=text("origin_stop_id IS NULL"),
            sqlite_where=text("origin_stop_id IS NULL"),
        ),
        Index(
            "ix_corridor_price_bands_segment_scope",
            "corridor_id",
            "service_type",
            "origin_stop_id",
            "destination_stop_id",
            unique=True,
            postgresql_where=text("origin_stop_id IS NOT NULL"),
            sqlite_where=text("origin_stop_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = _pk()
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    corridor_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("service_corridors.id", name="fk_corridor_price_bands_corridor"), nullable=False
    )
    service_type: Mapped[str] = mapped_column(Text, nullable=False)
    price_basis: Mapped[str] = mapped_column(Text, nullable=False)
    origin_stop_id: Mapped[int | None] = mapped_column(BigId, ForeignKey("corridor_stops.id", name="fk_corridor_price_bands_origin_stop"))
    destination_stop_id: Mapped[int | None] = mapped_column(
        BigId, ForeignKey("corridor_stops.id", name="fk_corridor_price_bands_destination_stop")
    )
    floor_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ceiling_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default=text("'UZS'"))
    enforced: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"),
        comment=(
            "Q90: false (default) means the band only warns and ranks - a negotiated price is never "
            "refused for being outside it. True is an admin-imposed abuse/safety limit and does refuse."
        ),
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id", name="fk_corridor_price_bands_updated_by"), nullable=False)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class CorridorPriceBandChange(Base):
    """Append-only; written only by the DB trigger on ``corridor_price_bands``."""

    __tablename__ = "corridor_price_band_changes"
    __table_args__ = (
        UniqueConstraint("band_id", "band_version", name="uq_corridor_price_band_changes_version"),
        Index("ix_corridor_price_band_changes_corridor", "corridor_id", "id"),
    )

    id: Mapped[int] = _pk()
    band_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("corridor_price_bands.id", name="fk_corridor_price_band_changes_band"), nullable=False
    )
    corridor_id: Mapped[int] = mapped_column(
        BigId, ForeignKey("service_corridors.id", name="fk_corridor_price_band_changes_corridor"), nullable=False
    )
    service_type: Mapped[str] = mapped_column(Text, nullable=False)
    origin_stop_id: Mapped[int | None] = mapped_column(
        BigId, ForeignKey("corridor_stops.id", name="fk_corridor_price_band_changes_origin_stop")
    )
    destination_stop_id: Mapped[int | None] = mapped_column(
        BigId, ForeignKey("corridor_stops.id", name="fk_corridor_price_band_changes_destination_stop")
    )
    band_version: Mapped[int] = mapped_column(Integer, nullable=False)
    old_floor_minor: Mapped[int | None] = mapped_column(BigInteger)
    old_ceiling_minor: Mapped[int | None] = mapped_column(BigInteger)
    old_is_active: Mapped[bool | None] = mapped_column(Boolean)
    new_floor_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    new_ceiling_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    new_is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", name="fk_corridor_price_band_changes_actor"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_at: Mapped[datetime] = _ts()


GEO_TABLES = GEO_TABLES + ("corridor_price_bands", "corridor_price_band_changes")
