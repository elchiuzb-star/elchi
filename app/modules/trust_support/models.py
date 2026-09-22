"""ORM mapping for trust & support tables created by migration 20260916_0060 (A12).

The migration is the source of truth: status CHECKs, the terminal-freeze and append-only guard triggers and the
evidence key guard live only in the database. Columns, unique constraints, indexes and foreign keys are mirrored
here (``tests/pg/trust_support/test_trust_schema_pg.py`` drift test). Types carry SQLite variants because the
legacy SQLite suite runs ``Base.metadata.create_all`` after this module may have been imported.

No ORM relationships across modules (ADR-0001); FK targets are imported so they resolve.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
import app.modules.bookings.models  # noqa: E402,F401  (FK targets: bookings, cash_receipts)
import app.modules.trips.models  # noqa: E402,F401  (FK target: trips)

BigIdentity = BigInteger().with_variant(Integer(), "sqlite")
JsonB = JSONB().with_variant(JSON(), "sqlite")
TextArray = ARRAY(Text()).with_variant(JSON(), "sqlite")

ACTIVE_DISPUTE_PREDICATE = "status IN ('open', 'under_review')"

TRUST_SUPPORT_TABLES: tuple[str, ...] = (
    "disputes_v2",
    "dispute_evidence",
    "contact_filter_hits",
    "contact_strikes",
    "trust_review_items",
    "support_tickets",
    "ratings_v2",
    "reputation_snapshots",
    # wave 6 (migration 20260917_0068): §8.1 blocks, §17.3 reports and fraud signals
    "user_blocks",
    "abuse_reports",
    "fraud_signals",
)


class DisputeV2(Base):
    __tablename__ = "disputes_v2"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_disputes_v2_public_id"),
        Index(
            "uq_disputes_v2_booking_type_active",
            "booking_id",
            "dispute_type",
            unique=True,
            postgresql_where=text(ACTIVE_DISPUTE_PREDICATE),
            sqlite_where=text(ACTIVE_DISPUTE_PREDICATE),
        ),
        Index("ix_disputes_v2_booking", "booking_id", "id"),
        Index("ix_disputes_v2_status_created", "status", "created_at", "id"),
        Index(
            "ix_disputes_v2_escalation_due",
            "escalate_at",
            "id",
            postgresql_where=text("status IN ('open', 'under_review') AND escalated_at IS NULL"),
            sqlite_where=text("status IN ('open', 'under_review') AND escalated_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    booking_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bookings.id", name="fk_disputes_v2_booking_id"), nullable=False
    )
    dispute_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'open'"))
    opened_by_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_disputes_v2_opened_by_user_id"), nullable=False
    )
    opened_by_side: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    cash_receipt_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cash_receipts.id", name="fk_disputes_v2_cash_receipt_id")
    )
    assigned_to: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", name="fk_disputes_v2_assigned_to"))
    resolution_code: Mapped[str | None] = mapped_column(String(32))
    resolution_text: Mapped[str | None] = mapped_column(Text)
    escalate_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", name="fk_disputes_v2_decided_by"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DisputeEvidence(Base):
    """Append-only (``append_only_violation``). ``file_ids`` are opaque upload references, ``note`` is masked."""

    __tablename__ = "dispute_evidence"
    __table_args__ = (Index("ix_dispute_evidence_dispute", "dispute_id", "id"),)

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    dispute_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("disputes_v2.id", name="fk_dispute_evidence_dispute_id"), nullable=False
    )
    author_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_dispute_evidence_author_user_id"), nullable=False
    )
    author_side: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    file_ids: Mapped[list[str]] = mapped_column(TextArray, nullable=False, server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ContactFilterHitRecord(Base):
    """Append-only log of consumed ``trust.contact_filter.hit`` events (Q45 window counting; no text)."""

    __tablename__ = "contact_filter_hits"
    __table_args__ = (
        UniqueConstraint("source_event_id", name="uq_contact_filter_hits_source_event"),
        Index("ix_contact_filter_hits_user_occurred", "user_id", "occurred_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_contact_filter_hits_user_id"), nullable=False
    )
    source_event_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    field: Mapped[str | None] = mapped_column(String(64))
    categories: Mapped[list[str]] = mapped_column(TextArray, nullable=False, server_default=text("'{}'"))
    match_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ContactStrike(Base):
    """Append-only (``append_only_violation``); ``UNIQUE(source_event_id)`` - one strike per hit event (Q45)."""

    __tablename__ = "contact_strikes"
    __table_args__ = (
        UniqueConstraint("source_event_id", name="uq_contact_strikes_source_event"),
        Index("ix_contact_strikes_user_occurred", "user_id", "occurred_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", name="fk_contact_strikes_user_id"), nullable=False)
    source_event_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    categories: Mapped[list[str]] = mapped_column(TextArray, nullable=False, server_default=text("'{}'"))
    reason_code: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TrustReviewItem(Base):
    __tablename__ = "trust_review_items"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_trust_review_items_public_id"),
        Index(
            "uq_trust_review_items_subject_signal_active",
            "subject_user_id",
            "signal_type",
            unique=True,
            postgresql_where=text(ACTIVE_DISPUTE_PREDICATE),
            sqlite_where=text(ACTIVE_DISPUTE_PREDICATE),
        ),
        Index("ix_trust_review_items_status_created", "status", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    subject_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_trust_review_items_subject_user_id"), nullable=False
    )
    signal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'open'"))
    evidence: Mapped[dict[str, Any]] = mapped_column(JsonB, nullable=False, server_default=text("'{}'"))
    signal_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    last_signal_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decision: Mapped[str | None] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text)
    assigned_to: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_trust_review_items_assigned_to")
    )
    decided_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_trust_review_items_decided_by")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SupportTicket(Base):
    __tablename__ = "support_tickets"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_support_tickets_public_id"),
        Index("ix_support_tickets_user_created", "user_id", "created_at", "id"),
        Index("ix_support_tickets_status_kind", "status", "kind", "id"),
        Index(
            "ix_support_tickets_open_sos_user",
            "user_id",
            postgresql_where=text("kind = 'sos' AND status <> 'resolved'"),
            sqlite_where=text("kind = 'sos' AND status <> 'resolved'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'open'"))
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", name="fk_support_tickets_user_id"), nullable=False)
    booking_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("bookings.id", name="fk_support_tickets_booking_id")
    )
    trip_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("trips.id", name="fk_support_tickets_trip_id"))
    message: Mapped[str | None] = mapped_column(Text)
    acknowledged_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_support_tickets_acknowledged_by")
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", name="fk_support_tickets_resolved_by"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    # BR M3: repeated SOS presses on an open SOS ticket (never a 429 in an emergency).
    press_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    last_pressed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RatingV2(Base):
    """§17.2: one rating per (booking, author, subject); only ``published_at`` (once) and ``moderation_status`` change."""

    __tablename__ = "ratings_v2"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_ratings_v2_public_id"),
        UniqueConstraint("booking_id", "author_user_id", "subject_user_id", name="uq_ratings_v2_booking_author_subject"),
        Index("ix_ratings_v2_subject_published", "subject_user_id", "service_type", "published_at"),
        Index(
            "ix_ratings_v2_unpublished",
            "booking_id",
            postgresql_where=text("published_at IS NULL"),
            sqlite_where=text("published_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    booking_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bookings.id", name="fk_ratings_v2_booking_id"), nullable=False
    )
    author_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_ratings_v2_author_user_id"), nullable=False
    )
    subject_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_ratings_v2_subject_user_id"), nullable=False
    )
    author_side: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_side: Mapped[str] = mapped_column(String(16), nullable=False)
    service_type: Mapped[str] = mapped_column(String(16), nullable=False)
    stars: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    moderation_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'visible'"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ReputationSnapshot(Base):
    __tablename__ = "reputation_snapshots"
    __table_args__ = (UniqueConstraint("user_id", "service_type", name="uq_reputation_snapshots_user_service"),)

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_reputation_snapshots_user_id"), nullable=False
    )
    service_type: Mapped[str] = mapped_column(String(16), nullable=False)
    rating_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    rating_sum: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    completed_bookings: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    completed_trips: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    eligible_resolved: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    on_time_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UserBlock(Base):
    """S9/S10 (§8.1). One row per direction; the read side treats a block as symmetric."""

    __tablename__ = "user_blocks"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_user_blocks_public_id"),
        UniqueConstraint("blocker_user_id", "blocked_user_id", name="uq_user_blocks_pair"),
        Index("ix_user_blocks_blocked", "blocked_user_id"),
        {
            "comment": (
                "§8.1: a block hides both users from each other in feed, proposals and accept. Symmetric on "
                "read, directional as a row; the blocked side is never told."
            )
        },
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    blocker_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="user_blocks_blocker_user_id_fkey"), nullable=False
    )
    blocked_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="user_blocks_blocked_user_id_fkey"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AbuseReport(Base):
    """S11/S12 (§17.3). ``details`` is stored contact-filtered (Q43); a report never acts on its own."""

    __tablename__ = "abuse_reports"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_abuse_reports_public_id"),
        Index("ix_abuse_reports_status", "status", "id"),
        Index("ix_abuse_reports_reporter_created", "reporter_user_id", "created_at"),
        {
            "comment": (
                "§17.3: a user report. details passes the contact filter before it is stored (Q43); a report "
                "never changes a booking, a rating or an account by itself - an operator reviews it."
            )
        },
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    reporter_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="abuse_reports_reporter_user_id_fkey"), nullable=False
    )
    subject_type: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", name="abuse_reports_subject_user_id_fkey")
    )
    reason_code: Mapped[str] = mapped_column(String(32), nullable=False)
    details: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'open'"))
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", name="abuse_reports_reviewed_by_fkey")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class FraudSignal(Base):
    """S12 (§17.3). What the platform noticed - counts and public ids only, opened for human review."""

    __tablename__ = "fraud_signals"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_fraud_signals_public_id"),
        UniqueConstraint("signal_type", "subject_user_id", "window_key", name="uq_fraud_signals_window"),
        Index("ix_fraud_signals_status", "status", "id"),
        {
            "comment": (
                "§17.3: what the platform noticed, never a verdict. window_key deduplicates one finding per "
                "window; evidence holds counts and public ids only (§15). No automatic block, rating change or "
                "payout follows."
            )
        },
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    signal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fraud_signals_subject_user_id_fkey"), nullable=False
    )
    window_key: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JsonB, nullable=False, server_default=text("'{}'"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'open'"))
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", name="fraud_signals_reviewed_by_fkey")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
