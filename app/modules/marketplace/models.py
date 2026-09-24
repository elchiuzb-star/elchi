"""ORM mapping for marketplace tables created by migrations 20260913_0039 and 20260913_0040.

Migrations are the source of truth: CHECKs (total formula, price basis, D9
parcel quantity), the open-thread and active-version partial unique indexes and
the proposal-version immutability trigger live in the database.

Cross-module foreign keys (geo stops/corridors/routes, wallet commission_policies) are
declared without ORM relationships (ADR-0001); their model modules are imported to resolve.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    JSON,
    BigInteger,
    Date,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
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

from app.db.base import Base
from app.modules.geo.models import Geometry
import app.modules.geo.models  # noqa: E402,F401  (FK targets)
import app.modules.trips.models  # noqa: E402,F401
import app.modules.wallet.models  # noqa: E402,F401  (FK target: commission_policies)

BigIdentity = BigInteger().with_variant(Integer(), "sqlite")
TextArray = ARRAY(Text()).with_variant(JSON(), "sqlite")

OPEN_TRIP_OFFER_PREDICATE = "kind = 'trip_offer' AND status NOT IN ('cancelled', 'expired')"


class Listing(Base):
    __tablename__ = "listings"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_listings_public_id"),
        Index(
            "uq_listings_open_trip_offer",
            "trip_id",
            "service_type",
            unique=True,
            postgresql_where=text(OPEN_TRIP_OFFER_PREDICATE),
            sqlite_where=text(OPEN_TRIP_OFFER_PREDICATE),
        ),
        # Q88 (0076): the partial indexes the migration creates, declared here so the ORM and the migrated
        # schema stay identical (`test_orm_metadata_matches_migrated_schema`).
        Index(
            "ix_listings_origin_district",
            "origin_district_id",
            postgresql_where=text("origin_district_id IS NOT NULL"),
            sqlite_where=text("origin_district_id IS NOT NULL"),
        ),
        Index(
            "ix_listings_destination_district",
            "destination_district_id",
            postgresql_where=text("destination_district_id IS NOT NULL"),
            sqlite_where=text("destination_district_id IS NOT NULL"),
        ),
        Index(
            "ix_listings_origin_point_gist",
            "origin_point",
            postgresql_using="gist",
            postgresql_where=text("origin_point IS NOT NULL"),
        ).ddl_if(dialect="postgresql"),
        Index(
            "ix_listings_destination_point_gist",
            "destination_point",
            postgresql_using="gist",
            postgresql_where=text("destination_point IS NOT NULL"),
        ).ddl_if(dialect="postgresql"),
        Index("ix_listings_feed", "service_type", "status", "departure_window_start", "id"),
        Index("ix_listings_corridor_status", "corridor_id", "status"),
        Index("ix_listings_owner_created", "owner_user_id", "created_at", "id"),
        Index("ix_listings_trip_id", "trip_id"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    owner_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_listings_owner_user_id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    service_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'draft'"))
    trip_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("trips.id", name="fk_listings_trip_id"))
    corridor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("service_corridors.id", name="fk_listings_corridor_id"), nullable=False
    )
    origin_stop_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("corridor_stops.id", name="fk_listings_origin_stop_id")
    )
    destination_stop_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("corridor_stops.id", name="fk_listings_destination_stop_id")
    )
    # Q88: an end is a verified stop **or** a place marked on the map (exactly one, CHECK in 0076).
    # A point carries the district it sits in, and the distance from the confirmed route it projects onto.
    origin_point: Mapped[Any | None] = mapped_column(
        Geometry("Point"), comment=(
            "Q88 (18.09.2026): a place marked on the map instead of a verified stop. Exactly one of origin_stop_id / origin_point is set. Matching projects it onto the confirmed route."
        )
    )
    origin_district_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("geo_districts.id", name="fk_listings_origin_district_id")
    )
    origin_address: Mapped[str | None] = mapped_column(Text)
    origin_route_offset_m: Mapped[int | None] = mapped_column(Integer)
    # Q88: an end is a verified stop **or** a place marked on the map (exactly one, CHECK in 0076).
    # A point carries the district it sits in, and the distance from the confirmed route it projects onto.
    destination_point: Mapped[Any | None] = mapped_column(
        Geometry("Point"), comment=(
            "Q88 (18.09.2026): a place marked on the map instead of a verified stop. Exactly one of destination_stop_id / destination_point is set. Matching projects it onto the confirmed route."
        )
    )
    destination_district_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("geo_districts.id", name="fk_listings_destination_district_id")
    )
    destination_address: Mapped[str | None] = mapped_column(Text)
    destination_route_offset_m: Mapped[int | None] = mapped_column(Integer)
    departure_window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    departure_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("'Asia/Tashkent'"))
    price_basis: Mapped[str] = mapped_column(String(16), nullable=False)
    unit_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default=text("'UZS'"))
    payment_method: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'cash'"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    created_by_operator_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_listings_created_by_operator_id")
    )
    consent_reference: Mapped[str | None] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    # Bumped only by proposal-invalidating edits (BR N1, migration 0045); A4 compares it at accept.
    terms_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_listings_cancelled_by_user_id")
    )
    cancelled_reason: Mapped[str | None] = mapped_column(String(64))
    cancel_comment: Mapped[str | None] = mapped_column(Text)
    # Q98: distinct people who opened this listing, denormalised from listing_views. Bumped only by the insert
    # that created a row there, and deliberately *not* part of `version` - looking at a listing is not an edit,
    # and a counter that moved the aggregate version would expire every open proposal on it (Q54).
    view_count: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("0"),
        # Kept byte-identical to migration 0083's COMMENT: the schema-drift gate compares them.
        comment=(
            "Q98: distinct people who opened this listing. Denormalised from listing_views and bumped only by "
            "the insert that created a row, so it cannot drift above the number of rows."
        ),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ListingView(Base):
    """One row per (listing, person) - the primary key is what makes the count a count of people (Q98).

    Written once, never updated: the first time somebody opens a listing. The owner, staff and anonymous
    readers are excluded by the caller, because a number that a refresh can raise is not a number the owner can
    act on (§9: no invented signals).
    """

    __tablename__ = "listing_views"
    __table_args__ = (
        Index("ix_listing_views_viewer", "viewer_user_id"),
        {
            "comment": (
                "Q98: one row per (listing, person) - the primary key is what makes the view count a count of "
                "people. Never written for the owner, for staff or for an anonymous reader."
            )
        },
    )

    listing_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("listings.id", name="listing_views_listing_id_fkey", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )
    viewer_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", name="listing_views_viewer_user_id_fkey", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )
    first_viewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PassengerListingDetails(Base):
    __tablename__ = "passenger_listing_details"

    listing_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("listings.id", name="fk_passenger_listing_details_listing_id", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )
    seat_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    adults: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    children: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    child_seat_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    baggage_pieces: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    baggage_total_weight_g: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    baggage_total_volume_ml: Mapped[int | None] = mapped_column(Integer)
    special_assistance: Mapped[str | None] = mapped_column(Text)
    amenities: Mapped[list[str]] = mapped_column(TextArray, nullable=False, server_default=text("'{}'"))


class ParcelListingDetails(Base):
    __tablename__ = "parcel_listing_details"

    listing_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("listings.id", name="fk_parcel_listing_details_listing_id", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )
    parcel_type: Mapped[str | None] = mapped_column(String(32))
    weight_g: Mapped[int | None] = mapped_column(Integer)
    length_cm: Mapped[int | None] = mapped_column(Integer)
    width_cm: Mapped[int | None] = mapped_column(Integer)
    height_cm: Mapped[int | None] = mapped_column(Integer)
    fragile: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    declared_value_minor: Mapped[int | None] = mapped_column(BigInteger)
    photo_file_id: Mapped[str | None] = mapped_column(String(255))
    payer: Mapped[str | None] = mapped_column(String(16))
    sender_name: Mapped[str | None] = mapped_column(String(120))
    sender_phone: Mapped[str | None] = mapped_column(String(32))
    receiver_name: Mapped[str | None] = mapped_column(String(120))
    receiver_phone: Mapped[str | None] = mapped_column(String(32))
    pickup_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pickup_window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dropoff_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dropoff_window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_weight_g: Mapped[int | None] = mapped_column(Integer)
    max_volume_ml: Mapped[int | None] = mapped_column(Integer)
    max_dimension_cm: Mapped[int | None] = mapped_column(Integer)
    accepted_parcel_types: Mapped[list[str]] = mapped_column(TextArray, nullable=False, server_default=text("'{}'"))


OPEN_THREAD_PREDICATE = "state = 'open'"
ACTIVE_VERSION_PREDICATE = "status = 'active'"


class ProposalThread(Base):
    __tablename__ = "proposal_threads"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_proposal_threads_public_id"),
        Index(
            "uq_proposal_threads_open_context",
            "listing_id",
            "client_user_id",
            "driver_user_id",
            "trip_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text(OPEN_THREAD_PREDICATE),
            sqlite_where=text(OPEN_THREAD_PREDICATE),
        ),
        Index("ix_proposal_threads_listing_state", "listing_id", "state", "id"),
        Index("ix_proposal_threads_client_user_id", "client_user_id", "id"),
        Index("ix_proposal_threads_driver_user_id", "driver_user_id", "id"),
        Index("ix_proposal_threads_trip_id", "trip_id"),
        # ADR-0025 (0091): offers made from one saved request
        Index(
            "ix_proposal_threads_trip_intent",
            "trip_intent_id",
            "state",
            postgresql_where=text("trip_intent_id IS NOT NULL"),
            sqlite_where=text("trip_intent_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    listing_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("listings.id", name="fk_proposal_threads_listing_id"), nullable=False
    )
    client_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_proposal_threads_client_user_id"), nullable=False
    )
    driver_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_proposal_threads_driver_user_id"), nullable=False
    )
    trip_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("trips.id", name="fk_proposal_threads_trip_id"))
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'open'"))
    current_version_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("proposal_versions.id", name="fk_proposal_threads_current_version_id", use_alter=True),
    )
    client_price_revisions: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    driver_price_revisions: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    closed_reason: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # ADR-0025 (0091): the saved request this offer was made from; both or neither, frozen once written (trigger)
    trip_intent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("trip_intents.id", name="fk_proposal_threads_trip_intent")
    )
    trip_intent_terms_version: Mapped[int | None] = mapped_column(Integer)


class ProposalVersion(Base):
    __tablename__ = "proposal_versions"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_proposal_versions_public_id"),
        UniqueConstraint("thread_id", "revision", name="uq_proposal_versions_thread_revision"),
        # Q88 (0076): the partial indexes the migration creates, declared here so the ORM and the migrated
        # schema stay identical (`test_orm_metadata_matches_migrated_schema`).
        Index(
            "ix_proposal_versions_pickup_district",
            "pickup_district_id",
            postgresql_where=text("pickup_district_id IS NOT NULL"),
            sqlite_where=text("pickup_district_id IS NOT NULL"),
        ),
        Index(
            "ix_proposal_versions_dropoff_district",
            "dropoff_district_id",
            postgresql_where=text("dropoff_district_id IS NOT NULL"),
            sqlite_where=text("dropoff_district_id IS NOT NULL"),
        ),
        Index(
            "uq_proposal_versions_active",
            "thread_id",
            unique=True,
            postgresql_where=text(ACTIVE_VERSION_PREDICATE),
            sqlite_where=text(ACTIVE_VERSION_PREDICATE),
        ),
        Index(
            "ix_proposal_versions_active_expires_at",
            "expires_at",
            postgresql_where=text(ACTIVE_VERSION_PREDICATE),
            sqlite_where=text(ACTIVE_VERSION_PREDICATE),
        ),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    thread_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("proposal_threads.id", name="fk_proposal_versions_thread_id"), nullable=False
    )
    revision: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    author_side: Mapped[str] = mapped_column(String(16), nullable=False)
    author_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_proposal_versions_author_user_id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'active'"))
    status_reason: Mapped[str | None] = mapped_column(String(64))
    pickup_stop_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("corridor_stops.id", name="fk_proposal_versions_pickup_stop_id")
    )
    dropoff_stop_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("corridor_stops.id", name="fk_proposal_versions_dropoff_stop_id")
    )
    # Q88: an end is a verified stop **or** a place marked on the map (exactly one, CHECK in 0076).
    # A point carries the district it sits in, and the distance from the confirmed route it projects onto.
    pickup_point: Mapped[Any | None] = mapped_column(
        Geometry("Point"), comment=(
            "Q88 (18.09.2026): a place marked on the map instead of a verified stop. Exactly one of pickup_stop_id / pickup_point is set. Matching projects it onto the confirmed route."
        )
    )
    pickup_district_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("geo_districts.id", name="fk_proposal_versions_pickup_district_id")
    )
    pickup_address: Mapped[str | None] = mapped_column(Text)
    pickup_route_offset_m: Mapped[int | None] = mapped_column(Integer)
    # Q88: an end is a verified stop **or** a place marked on the map (exactly one, CHECK in 0076).
    # A point carries the district it sits in, and the distance from the confirmed route it projects onto.
    dropoff_point: Mapped[Any | None] = mapped_column(
        Geometry("Point"), comment=(
            "Q88 (18.09.2026): a place marked on the map instead of a verified stop. Exactly one of dropoff_stop_id / dropoff_point is set. Matching projects it onto the confirmed route."
        )
    )
    dropoff_district_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("geo_districts.id", name="fk_proposal_versions_dropoff_district_id")
    )
    dropoff_address: Mapped[str | None] = mapped_column(Text)
    dropoff_route_offset_m: Mapped[int | None] = mapped_column(Integer)
    pickup_occurrence_seq: Mapped[int | None] = mapped_column(SmallInteger)
    dropoff_occurrence_seq: Mapped[int | None] = mapped_column(SmallInteger)
    pickup_window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pickup_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price_basis: Mapped[str] = mapped_column(String(16), nullable=False)
    unit_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default=text("'UZS'"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    listing_version: Mapped[int] = mapped_column(Integer, nullable=False)
    listing_terms_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    trip_version: Mapped[int | None] = mapped_column(Integer)
    route_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("route_versions.id", name="fk_proposal_versions_route_version_id")
    )
    fee_policy_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("commission_policies.id", name="fk_proposal_versions_fee_policy_id"), nullable=False
    )
    fee_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    commission_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Demand snapshot (migration 0044): capacity is checked from it and A4 reserves from it.
    baggage_ml: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cargo_weight_g: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cargo_volume_ml: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    parcel_length_cm: Mapped[int | None] = mapped_column(Integer)
    parcel_width_cm: Mapped[int | None] = mapped_column(Integer)
    parcel_height_cm: Mapped[int | None] = mapped_column(Integer)
    # Receiver contact of a trip-offer parcel proposal (migration 0054): only the proposing client sees it (Q43/Q44).
    receiver_name: Mapped[str | None] = mapped_column(String(120))
    receiver_phone: Mapped[str | None] = mapped_column(String(32))


class ListingOfferLabel(Base):
    """Stable anonymous ordinal per (listing, driver) for the open auction view (R1, migration 0045)."""

    __tablename__ = "listing_offer_labels"
    __table_args__ = (
        UniqueConstraint("listing_id", "driver_user_id", name="uq_listing_offer_labels_listing_driver"),
        UniqueConstraint("listing_id", "label_seq", name="uq_listing_offer_labels_listing_seq"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    listing_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("listings.id", name="fk_listing_offer_labels_listing_id", ondelete="CASCADE"),
        nullable=False,
    )
    driver_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_listing_offer_labels_driver_user_id"), nullable=False
    )
    label_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ParcelPolicyVersion(Base):
    """§5.2 approved prohibited/restricted items policy (migration 20260917_0070).

    A draft is staff-only; ``active`` requires a super_admin confirmation, and only one version is active at a
    time. The absence of an approved version is a *refusal to start new parcel business*, never permission.
    """

    __tablename__ = "parcel_policy_versions"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_parcel_policy_versions_public_id"),
        UniqueConstraint("label", name="uq_parcel_policy_versions_label"),
        Index(
            "uq_parcel_policy_versions_active",
            "status",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        {
            "comment": (
                "§5.2: the approved prohibited/restricted items policy. A draft is staff-only; active needs a "
                "super_admin confirmation. No approved version = no NEW parcel business in production "
                "(fail-closed), while existing bookings finish."
            )
        },
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'draft'"))
    source_note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="parcel_policy_versions_created_by_fkey"), nullable=False
    )
    confirmed_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", name="parcel_policy_versions_confirmed_by_fkey")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class ParcelPolicyItem(Base):
    """One rule of a policy version. A ``prohibited`` row must name its legal basis and source (DB CHECK)."""

    __tablename__ = "parcel_policy_items"
    __table_args__ = (
        UniqueConstraint("policy_version_id", "code", name="uq_parcel_policy_items_code"),
        Index("ix_parcel_policy_items_version", "policy_version_id", "display_order", "id"),
        {
            "comment": (
                "§5.2 rules of one policy version. A `prohibited` row must carry its legal basis and source "
                "(CHECK): the platform never tells a user something is illegal without naming why and where "
                "that comes from."
            )
        },
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    policy_version_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("parcel_policy_versions.id", name="parcel_policy_items_policy_version_id_fkey", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    applies_to: Mapped[str] = mapped_column(String(24), nullable=False, server_default=text("'parcel'"))
    title_uz: Mapped[str] = mapped_column(Text, nullable=False)
    description_uz: Mapped[str] = mapped_column(Text, nullable=False)
    legal_basis: Mapped[str | None] = mapped_column(Text)
    source_ref: Mapped[str | None] = mapped_column(Text)
    source_checked_on: Mapped[date | None] = mapped_column(Date)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("100"))


class TripIntent(Base):
    """ADR-0025: a client's private, reusable trip/parcel request (never a public listing; nothing is sent by itself).

    ``terms_version`` moves only with a material edit (ends, window, quantity, parcel, receiver); offers remember it and
    are accepted only while it is unchanged. ``status = booked`` exactly while ``booking_id`` is set (CHECK)."""

    __tablename__ = "trip_intents"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_trip_intents_public_id"),
        Index("ix_trip_intents_owner_status", "owner_user_id", "status", "id"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    owner_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", name="fk_trip_intents_owner"), nullable=False)
    service_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'active'"))
    current_version_no: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    terms_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    booking_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("bookings.id", name="fk_trip_intents_booking"))
    closed_reason: Mapped[str | None] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TripIntentVersion(Base):
    """ADR-0025: one immutable version of a saved request's terms (append-only trigger)."""

    __tablename__ = "trip_intent_versions"
    __table_args__ = (UniqueConstraint("intent_id", "version_no", name="uq_trip_intent_versions_no"),)

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    intent_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("trip_intents.id", name="fk_trip_intent_versions_intent"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    terms_version: Mapped[int] = mapped_column(Integer, nullable=False)
    origin_stop_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("corridor_stops.id", name="fk_trip_intent_versions_origin_stop")
    )
    origin_district_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("geo_districts.id", name="fk_trip_intent_versions_origin_district")
    )
    origin_lat: Mapped[Any | None] = mapped_column(Numeric(10, 7))
    origin_lng: Mapped[Any | None] = mapped_column(Numeric(10, 7))
    origin_address: Mapped[str | None] = mapped_column(String(500))
    destination_stop_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("corridor_stops.id", name="fk_trip_intent_versions_destination_stop")
    )
    destination_district_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("geo_districts.id", name="fk_trip_intent_versions_destination_district")
    )
    destination_lat: Mapped[Any | None] = mapped_column(Numeric(10, 7))
    destination_lng: Mapped[Any | None] = mapped_column(Numeric(10, 7))
    destination_address: Mapped[str | None] = mapped_column(String(500))
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    quantity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    price_basis: Mapped[str | None] = mapped_column(String(16))
    unit_price_minor: Mapped[int | None] = mapped_column(BigInteger)
    parcel_type: Mapped[str | None] = mapped_column(String(32))
    weight_g: Mapped[int | None] = mapped_column(Integer)
    length_cm: Mapped[int | None] = mapped_column(Integer)
    width_cm: Mapped[int | None] = mapped_column(Integer)
    height_cm: Mapped[int | None] = mapped_column(Integer)
    receiver_name: Mapped[str | None] = mapped_column(String(120))
    receiver_phone: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
