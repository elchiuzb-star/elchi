"""ORM mapping for booking tables created by migrations 20260915_0048 .. 20260915_0051 (A4).

Migrations are the source of truth: status CHECKs, the D3 exempt CHECK, the agreement-snapshot guard trigger,
the release-contract guard and the deferred capacity-consistency trigger live only in the database. Columns,
unique constraints, indexes and foreign keys are mirrored here (ORM drift test).

Cross-module foreign keys (users, trips, listings, proposals, geo, commission policies) are declared without
ORM relationships (ADR-0001); their model modules are imported so the targets resolve.
"""

from __future__ import annotations

import uuid
from datetime import datetime
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
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.modules.geo.models import Geometry
import app.modules.geo.models  # noqa: E402,F401  (FK targets: corridor_stops, route_versions, service_corridors)
import app.modules.marketplace.models  # noqa: E402,F401  (FK targets: listings, proposal_threads, proposal_versions)
import app.modules.trips.models  # noqa: E402,F401  (FK target: trips)
import app.modules.wallet.models  # noqa: E402,F401  (FK target: commission_policies)

BigIdentity = BigInteger().with_variant(Integer(), "sqlite")
JsonB = JSONB().with_variant(JSON(), "sqlite")
TextArray = ARRAY(Text()).with_variant(JSON(), "sqlite")

TERMINAL_SERVICE_PREDICATE = "service_status NOT IN ('completed', 'cancelled', 'no_show', 'returned')"


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_bookings_public_id"),
        UniqueConstraint("accepted_proposal_version_id", name="uq_bookings_accepted_proposal_version"),
        # ADR-0025 (0091): one non-cancelled booking per saved trip/parcel request
        Index(
            "uq_bookings_trip_intent_binding",
            "trip_intent_id",
            unique=True,
            postgresql_where=text("trip_intent_id IS NOT NULL AND service_status <> 'cancelled'"),
            sqlite_where=text("trip_intent_id IS NOT NULL AND service_status <> 'cancelled'"),
        ),
        Index(
            "uq_bookings_request_listing_binding",
            "request_listing_id",
            unique=True,
            postgresql_where=text("request_listing_id IS NOT NULL AND service_status <> 'cancelled'"),
            sqlite_where=text("request_listing_id IS NOT NULL AND service_status <> 'cancelled'"),
        ),
        # Q88 (0076): the partial indexes the migration creates, declared here so the ORM and the migrated
        # schema stay identical (`test_orm_metadata_matches_migrated_schema`).
        Index(
            "ix_bookings_pickup_district",
            "pickup_district_id",
            postgresql_where=text("pickup_district_id IS NOT NULL"),
            sqlite_where=text("pickup_district_id IS NOT NULL"),
        ),
        Index(
            "ix_bookings_dropoff_district",
            "dropoff_district_id",
            postgresql_where=text("dropoff_district_id IS NOT NULL"),
            sqlite_where=text("dropoff_district_id IS NOT NULL"),
        ),
        Index("ix_bookings_client_created", "client_user_id", "created_at", "id"),
        Index("ix_bookings_driver_created", "driver_user_id", "created_at", "id"),
        Index("ix_bookings_trip_id", "trip_id"),
        Index("ix_bookings_corridor_status", "corridor_id", "service_status"),
        Index("ix_bookings_supply_listing_id", "supply_listing_id"),
        Index(
            "ix_bookings_client_open",
            "client_user_id",
            postgresql_where=text(TERMINAL_SERVICE_PREDICATE),
            sqlite_where=text(TERMINAL_SERVICE_PREDICATE),
        ),
        Index(
            "ix_bookings_driver_open",
            "driver_user_id",
            postgresql_where=text(TERMINAL_SERVICE_PREDICATE),
            sqlite_where=text(TERMINAL_SERVICE_PREDICATE),
        ),
        Index(
            "ix_bookings_finance_review",
            "id",
            postgresql_where=text("finance_review_reason IS NOT NULL AND commission_status = 'held'"),
            sqlite_where=text("finance_review_reason IS NOT NULL AND commission_status = 'held'"),
        ),
        Index(
            "ix_bookings_awaiting_confirmation",
            "service_ended_at",
            "id",
            postgresql_where=text("service_status IN ('arrived', 'delivered')"),
            sqlite_where=text("service_status IN ('arrived', 'delivered')"),
        ),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    service_type: Mapped[str] = mapped_column(String(16), nullable=False)
    service_status: Mapped[str] = mapped_column(String(24), nullable=False)
    cash_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'unpaid'"))
    commission_status: Mapped[str] = mapped_column(String(24), nullable=False)
    client_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_bookings_client_user_id"), nullable=False
    )
    driver_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_bookings_driver_user_id"), nullable=False
    )
    trip_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("trips.id", name="fk_bookings_trip_id"), nullable=False)
    corridor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("service_corridors.id", name="fk_bookings_corridor_id"), nullable=False
    )
    request_listing_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("listings.id", name="fk_bookings_request_listing_id")
    )
    supply_listing_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("listings.id", name="fk_bookings_supply_listing_id")
    )
    proposal_thread_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("proposal_threads.id", name="fk_bookings_proposal_thread_id"), nullable=False
    )
    # ADR-0025 (0091): the saved request of the accepted offer (equal to the thread's, frozen - trigger)
    trip_intent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("trip_intents.id", name="fk_bookings_trip_intent")
    )
    accepted_proposal_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("proposal_versions.id", name="fk_bookings_accepted_proposal_version_id"), nullable=False
    )
    route_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("route_versions.id", name="fk_bookings_route_version_id"), nullable=False
    )
    trip_version: Mapped[int] = mapped_column(Integer, nullable=False)
    pickup_stop_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("corridor_stops.id", name="fk_bookings_pickup_stop_id")
    )
    dropoff_stop_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("corridor_stops.id", name="fk_bookings_dropoff_stop_id")
    )
    # Q88: an end is a verified stop **or** a place marked on the map (exactly one, CHECK in 0076).
    # A point carries the district it sits in, and the distance from the confirmed route it projects onto.
    pickup_point: Mapped[Any | None] = mapped_column(
        Geometry("Point"), comment=(
            "Q88 (18.09.2026): a place marked on the map instead of a verified stop. Exactly one of pickup_stop_id / pickup_point is set. Matching projects it onto the confirmed route."
        )
    )
    pickup_district_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("geo_districts.id", name="fk_bookings_pickup_district_id")
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
        BigInteger, ForeignKey("geo_districts.id", name="fk_bookings_dropoff_district_id")
    )
    dropoff_address: Mapped[str | None] = mapped_column(Text)
    dropoff_route_offset_m: Mapped[int | None] = mapped_column(Integer)
    pickup_occurrence_seq: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    dropoff_occurrence_seq: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    pickup_window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pickup_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dropoff_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dropoff_window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    seats: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    baggage_ml: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cargo_weight_g: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cargo_volume_ml: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    price_basis: Mapped[str] = mapped_column(String(16), nullable=False)
    unit_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default=text("'UZS'"))
    payment_method: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'cash'"))
    fee_policy_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("commission_policies.id", name="fk_bookings_fee_policy_id"), nullable=False
    )
    fee_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    commission_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    listing_version: Mapped[int] = mapped_column(Integer, nullable=False)
    listing_terms_version: Mapped[int] = mapped_column(Integer, nullable=False)
    terms_snapshot: Mapped[dict[str, Any]] = mapped_column(JsonB, nullable=False)
    arrived_at_pickup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    service_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    service_ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    service_terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by_side: Mapped[str | None] = mapped_column(String(16))
    cancelled_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_bookings_cancelled_by_user_id")
    )
    cancel_reason_code: Mapped[str | None] = mapped_column(String(64))
    cancel_comment: Mapped[str | None] = mapped_column(Text)
    fault_side: Mapped[str | None] = mapped_column(String(16))
    # Q66 (0056): commission kept held after completion for finance review (CommissionReviewReason).
    finance_review_reason: Mapped[str | None] = mapped_column(String(48))
    finance_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BookingProofReissue(Base):
    """Append-only proof code reissue history (0056, BR blocker 3). Never stores a code."""

    __tablename__ = "booking_proof_reissues"
    __table_args__ = (Index("ix_booking_proof_reissues_booking", "booking_id", "proof_kind", "created_at"),)

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bookings.id", name="fk_booking_proof_reissues_booking_id"), nullable=False
    )
    proof_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    from_rotation: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    to_rotation: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    actor_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_booking_proof_reissues_actor_user_id"), nullable=False
    )
    actor_side: Mapped[str] = mapped_column(String(16), nullable=False)
    self_service: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BookingAllocation(Base):
    __tablename__ = "booking_allocations"
    __table_args__ = (
        Index(
            "uq_booking_allocations_booking_segment_active",
            "booking_id",
            "segment_from_seq",
            unique=True,
            postgresql_where=text("active"),
            sqlite_where=text("active"),
        ),
        Index("ix_booking_allocations_booking", "booking_id", "id"),
        Index(
            "ix_booking_allocations_trip_active",
            "trip_id",
            "segment_from_seq",
            postgresql_where=text("active"),
            sqlite_where=text("active"),
        ),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bookings.id", name="fk_booking_allocations_booking_id"), nullable=False
    )
    trip_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("trips.id", name="fk_booking_allocations_trip_id"), nullable=False
    )
    segment_from_seq: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    seats: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    baggage_ml: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cargo_weight_g: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cargo_volume_ml: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BookingStatusHistory(Base):
    __tablename__ = "booking_status_history"
    __table_args__ = (Index("ix_booking_status_history_booking", "booking_id", "id"),)

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bookings.id", name="fk_booking_status_history_booking_id"), nullable=False
    )
    machine: Mapped[str] = mapped_column(String(24), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(24))
    to_status: Mapped[str] = mapped_column(String(24), nullable=False)
    command: Mapped[str] = mapped_column(String(48), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_booking_status_history_actor_user_id")
    )
    actor_side: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BookingProof(Base):
    __tablename__ = "booking_proofs"
    __table_args__ = (UniqueConstraint("booking_id", "proof_kind", name="uq_booking_proofs_booking_kind"),)

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bookings.id", name="fk_booking_proofs_booking_id"), nullable=False
    )
    proof_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    code_rotation: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    key_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("1"))
    failed_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    code_hash: Mapped[str | None] = mapped_column(CHAR(64))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actor_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", name="fk_booking_proofs_actor_user_id"))
    evidence_file_ids: Mapped[list[str]] = mapped_column(TextArray, nullable=False, server_default=text("'{}'"))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BookingProofAttempt(Base):
    __tablename__ = "booking_proof_attempts"
    __table_args__ = (Index("ix_booking_proof_attempts_booking", "booking_id", "proof_kind", "id"),)

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bookings.id", name="fk_booking_proof_attempts_booking_id"), nullable=False
    )
    proof_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    code_rotation: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    actor_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_booking_proof_attempts_actor_user_id"), nullable=False
    )
    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class NoShowReview(Base):
    __tablename__ = "no_show_reviews"
    __table_args__ = (
        Index(
            "uq_no_show_reviews_pending",
            "booking_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
        Index("ix_no_show_reviews_booking", "booking_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bookings.id", name="fk_no_show_reviews_booking_id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'pending'"))
    reported_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_no_show_reviews_reported_by"), nullable=False
    )
    arrived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    wait_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    contact_attempts: Mapped[list[dict[str, Any]]] = mapped_column(JsonB, nullable=False, server_default=text("'[]'"))  # portable; the migration casts to jsonb
    evidence_file_ids: Mapped[list[str]] = mapped_column(TextArray, nullable=False, server_default=text("'{}'"))
    note: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", name="fk_no_show_reviews_decided_by"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_command: Mapped[str | None] = mapped_column(String(32))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CustodyCase(Base):
    __tablename__ = "custody_cases"
    __table_args__ = (
        Index(
            "uq_custody_cases_open",
            "booking_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
            sqlite_where=text("status = 'open'"),
        ),
        Index("ix_custody_cases_booking", "booking_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bookings.id", name="fk_custody_cases_booking_id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'open'"))
    opened_reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    opened_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", name="fk_custody_cases_opened_by"))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", name="fk_custody_cases_resolved_by"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CashReceipt(Base):
    __tablename__ = "cash_receipts"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_cash_receipts_public_id"),
        Index(
            "uq_cash_receipts_open",
            "booking_id",
            unique=True,
            postgresql_where=text("status IN ('reported_paid', 'contested')"),
            sqlite_where=text("status IN ('reported_paid', 'contested')"),
        ),
        Index("ix_cash_receipts_booking", "booking_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    booking_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bookings.id", name="fk_cash_receipts_booking_id"), nullable=False
    )
    reported_by_side: Mapped[str] = mapped_column(String(16), nullable=False)
    reported_by_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_cash_receipts_reported_by_user_id"), nullable=False
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default=text("'UZS'"))
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default=text("'reported_paid'"))
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    decided_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_cash_receipts_decided_by_user_id")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_comment: Mapped[str | None] = mapped_column(Text)
    dispute_id: Mapped[int | None] = mapped_column(BigInteger)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BookingAmendment(Base):
    __tablename__ = "booking_amendments"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_booking_amendments_public_id"),
        Index(
            "uq_booking_amendments_proposed",
            "booking_id",
            unique=True,
            postgresql_where=text("status = 'proposed'"),
            sqlite_where=text("status = 'proposed'"),
        ),
        Index("ix_booking_amendments_booking", "booking_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    booking_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bookings.id", name="fk_booking_amendments_booking_id"), nullable=False
    )
    booking_version: Mapped[int] = mapped_column(Integer, nullable=False)
    author_side: Mapped[str] = mapped_column(String(16), nullable=False)
    author_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_booking_amendments_author_user_id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'proposed'"))
    changes: Mapped[dict[str, Any]] = mapped_column(JsonB, nullable=False)
    new_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    new_unit_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    new_total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fee_delta_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_booking_amendments_decided_by_user_id")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
