"""ORM mapping for the promotions tables (migrations 20260923_0084-0088, ADR-0023).

The migration owns CHECK constraints, triggers (append-only ledger, trigger-written budget cache, activation and
state guards, deferred balance checks) and the reconciliation view; these classes mirror columns, unique
constraints, foreign keys and indexes for the ORM drift check and stay SQLite-creatable.
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
    ForeignKeyConstraint,
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

import app.models  # noqa: F401  (FK target: users)
import app.modules.bookings.models  # noqa: F401  (FK target: bookings)
from app.db.base import Base

BigIdentity = BigInteger().with_variant(Integer(), "sqlite")
JsonB = JSONB().with_variant(JSON(), "sqlite")


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PromoCampaign(Base):
    __tablename__ = "promo_campaigns"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_promo_campaigns_public_id"),
        ForeignKeyConstraint(
            ["active_version_id", "id"],
            ["promo_campaign_versions.id", "promo_campaign_versions.campaign_id"],
            name="fk_promo_campaigns_active_version",
            use_alter=True,
        ),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    family: Mapped[str] = mapped_column(String(32), nullable=False)
    service_type: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default=text("'UZS'"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'draft'"))
    active_version_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_promo_campaigns_created_by"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _created_at()
    # 0086: an operational stop of qualification/grant processing; deletes nothing
    processing_suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_suspend_reason: Mapped[str | None] = mapped_column(Text)


class PromoCampaignVersion(Base):
    """Append-only (DB trigger). New terms are a new version; enrollments pin the version they joined (QA #22)."""

    __tablename__ = "promo_campaign_versions"
    __table_args__ = (
        UniqueConstraint("campaign_id", "version_no", name="uq_promo_campaign_versions_campaign_no"),
        UniqueConstraint("id", "campaign_id", name="uq_promo_campaign_versions_id_campaign"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("promo_campaigns.id", name="fk_promo_campaign_versions_campaign"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    referrer_reward_minor: Mapped[int | None] = mapped_column(BigInteger)
    referee_reward_minor: Mapped[int | None] = mapped_column(BigInteger)
    referrer_instrument: Mapped[str | None] = mapped_column(String(16))
    referee_instrument: Mapped[str | None] = mapped_column(String(16))
    milestone_thresholds: Mapped[Any | None] = mapped_column(JsonB)
    min_distinct_clients: Mapped[int | None] = mapped_column(Integer)
    enrollment_limit: Mapped[int | None] = mapped_column(Integer)
    qualification_window_s: Mapped[int | None] = mapped_column(Integer)
    reward_validity_s: Mapped[int | None] = mapped_column(Integer)
    review_sla_s: Mapped[int | None] = mapped_column(Integer)
    restoration_grace_s: Mapped[int | None] = mapped_column(Integer)
    max_discount_share_bps: Mapped[int | None] = mapped_column(Integer)
    max_discount_per_booking_minor: Mapped[int | None] = mapped_column(BigInteger)
    passenger_bonus_max_per_booking_minor: Mapped[int | None] = mapped_column(BigInteger)
    driver_credit_max_per_booking_minor: Mapped[int | None] = mapped_column(BigInteger)
    variable_cost_fixed_minor: Mapped[int | None] = mapped_column(BigInteger)
    variable_cost_bps: Mapped[int | None] = mapped_column(Integer)
    min_margin_minor: Mapped[int | None] = mapped_column(BigInteger)
    approval_reference: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_promo_campaign_versions_created_by"), nullable=False
    )
    created_at: Mapped[datetime] = _created_at()


class PromoBudget(Base):
    """Cache of the promo ledger per campaign; written only by the ledger trigger (DB guard)."""

    __tablename__ = "promo_budgets"
    __table_args__ = (UniqueConstraint("campaign_id", name="uq_promo_budgets_campaign"),)

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("promo_campaigns.id", name="fk_promo_budgets_campaign"), nullable=False
    )
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default=text("'UZS'"))
    allocated_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    promised_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    granted_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    consumed_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    released_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    last_ledger_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = _created_at()


class PromoBudgetRequest(Base):
    __tablename__ = "promo_budget_requests"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_promo_budget_requests_public_id"),
        ForeignKeyConstraint(
            ["ledger_transaction_id"],
            ["promo_ledger_transactions.id"],
            name="fk_promo_budget_requests_ledger_transaction",
            use_alter=True,
        ),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, default=uuid.uuid4)
    campaign_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("promo_campaigns.id", name="fk_promo_budget_requests_campaign"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default=text("'UZS'"))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_reference: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'pending'"))
    requested_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_promo_budget_requests_requested_by"), nullable=False
    )
    approved_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_promo_budget_requests_approved_by")
    )
    rejected_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_promo_budget_requests_rejected_by")
    )
    reject_reason: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ledger_transaction_id: Mapped[int | None] = mapped_column(BigInteger)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _created_at()


class PromoObligation(Base):
    """One beneficiary's reward. Promise, grant and spending are stages of this one obligation (Q115)."""

    __tablename__ = "promo_obligations"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_promo_obligations_public_id"),
        UniqueConstraint("reward_key", name="uq_promo_obligations_reward_key"),
        ForeignKeyConstraint(
            ["campaign_version_id", "campaign_id"],
            ["promo_campaign_versions.id", "promo_campaign_versions.campaign_id"],
            name="fk_promo_obligations_version",
        ),
        Index("ix_promo_obligations_campaign_status", "campaign_id", "status"),
        Index("ix_promo_obligations_beneficiary", "beneficiary_user_id", "status"),
        Index("ix_promo_obligations_enrollment", "enrollment_id"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, default=uuid.uuid4)
    campaign_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("promo_campaigns.id", name="fk_promo_obligations_campaign"), nullable=False
    )
    campaign_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    beneficiary_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_promo_obligations_beneficiary"), nullable=False
    )
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    milestone: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    instrument: Mapped[str] = mapped_column(String(16), nullable=False)
    service_type: Mapped[str] = mapped_column(String(16), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reward_key: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'promised'"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _created_at()
    # 0085: the enrollment that promised it (NULL only for obligations created outside an enrollment)
    enrollment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("promo_enrollments.id", name="fk_promo_obligations_enrollment", use_alter=True)
    )


class PromoLot(Base):
    """A granted bonus/credit. ``amount = available + reserved + consumed + expired + reversed`` (DB CHECK)."""

    __tablename__ = "promo_lots"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_promo_lots_public_id"),
        UniqueConstraint("obligation_id", name="uq_promo_lots_obligation"),
        Index("ix_promo_lots_owner_status", "owner_user_id", "status"),
        Index("ix_promo_lots_status_expires", "status", "expires_at"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, default=uuid.uuid4)
    obligation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("promo_obligations.id", name="fk_promo_lots_obligation"), nullable=False
    )
    campaign_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("promo_campaigns.id", name="fk_promo_lots_campaign"), nullable=False
    )
    owner_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_promo_lots_owner"), nullable=False
    )
    instrument: Mapped[str] = mapped_column(String(16), nullable=False)
    service_type: Mapped[str] = mapped_column(String(16), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default=text("'UZS'"))
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reserved_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    consumed_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    expired_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    reversed_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'pending_review'"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 0086: spend period start
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _created_at()


class PromoRedemption(Base):
    __tablename__ = "promo_redemptions"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_promo_redemptions_public_id"),
        UniqueConstraint("lot_id", "booking_id", "terms_seq", name="uq_promo_redemptions_lot_booking_seq"),
        Index("ix_promo_redemptions_booking", "booking_id"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, default=uuid.uuid4)
    lot_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("promo_lots.id", name="fk_promo_redemptions_lot"), nullable=False
    )
    booking_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bookings.id", name="fk_promo_redemptions_booking"), nullable=False
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    terms_seq: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))  # 0087: which agreement
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'reserved'"))
    release_fault: Mapped[str | None] = mapped_column(String(16))  # client|driver|platform|none|undetermined (0089)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 0089 (Q129): a grace extension this release gave the lot - from which expiry to which
    restored_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    restored_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = _created_at()


class PromoLedgerTransaction(Base):
    """Append-only (DB trigger). Every budget movement; corrections are new rows, never edits."""

    __tablename__ = "promo_ledger_transactions"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_promo_ledger_transactions_public_id"),
        UniqueConstraint("reference_key", name="uq_promo_ledger_transactions_reference_key"),
        Index("uq_promo_ledger_promise_obligation", "obligation_id", unique=True,
              postgresql_where=text("kind = 'promise'"), sqlite_where=text("kind = 'promise'")),
        Index("uq_promo_ledger_grant_lot", "lot_id", unique=True,
              postgresql_where=text("kind = 'grant'"), sqlite_where=text("kind = 'grant'")),
        Index("uq_promo_ledger_consume_redemption", "redemption_id", unique=True,
              postgresql_where=text("kind = 'consume'"), sqlite_where=text("kind = 'consume'")),
        Index("ix_promo_ledger_transactions_campaign", "campaign_id", "id"),
        Index("uq_promo_ledger_reinstate_once", "reinstates_id", unique=True,
              postgresql_where=text("kind = 'reinstate'"), sqlite_where=text("kind = 'reinstate'")),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, default=uuid.uuid4)
    campaign_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("promo_campaigns.id", name="fk_promo_ledger_transactions_campaign"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default=text("'UZS'"))
    reference_key: Mapped[str] = mapped_column(String(200), nullable=False)
    reversal_of_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("promo_ledger_transactions.id", name="fk_promo_ledger_transactions_reversal")
    )
    obligation_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("promo_obligations.id", name="fk_promo_ledger_transactions_obligation")
    )
    lot_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("promo_lots.id", name="fk_promo_ledger_transactions_lot")
    )
    redemption_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("promo_redemptions.id", name="fk_promo_ledger_transactions_redemption")
    )
    budget_request_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("promo_budget_requests.id", name="fk_promo_ledger_transactions_request")
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_promo_ledger_transactions_actor")
    )
    reason: Mapped[str | None] = mapped_column(Text)
    budget_seq: Mapped[int | None] = mapped_column(BigInteger)
    reinstates_id: Mapped[int | None] = mapped_column(  # 0086: the exact expiry release a reinstatement undoes
        BigInteger, ForeignKey("promo_ledger_transactions.id", name="fk_promo_ledger_transactions_reinstates")
    )
    created_at: Mapped[datetime] = _created_at()


# --- referral stage 2 (migration 20260923_0085) ------------------------------------------------------------------


class PromoIdentity(Base):
    """One person as far as acquisition rewards are concerned (Q108). Holds no phone and no key."""

    __tablename__ = "promo_identities"
    __table_args__ = (
        Index("uq_promo_identities_current_user", "current_user_id", unique=True,
              postgresql_where=text("current_user_id IS NOT NULL"), sqlite_where=text("current_user_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    current_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_promo_identities_current_user")
    )
    first_window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retain_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _created_at()


class PromoIdentityDigest(Base):
    """HMAC digest of the normalised phone under one key version (never the key, never the phone)."""

    __tablename__ = "promo_identity_digests"
    __table_args__ = (
        UniqueConstraint("key_version", "digest", name="uq_promo_identity_digests_version_digest"),
        UniqueConstraint("identity_id", "key_version", name="uq_promo_identity_digests_identity_version"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    identity_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("promo_identities.id", name="fk_promo_identity_digests_identity"), nullable=False
    )
    key_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    digest: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = _created_at()


class ReferralCode(Base):
    __tablename__ = "referral_codes"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_referral_codes_public_id"),
        UniqueConstraint("code", name="uq_referral_codes_code"),
        Index("uq_referral_codes_one_active_per_owner", "owner_user_id", unique=True,
              postgresql_where=text("status = 'active'"), sqlite_where=text("status = 'active'")),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    owner_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_referral_codes_owner"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'active'"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class ReferralAttribution(Base):
    """Who invited whom - one per (referee, family), first wins, immutable (DB trigger)."""

    __tablename__ = "referral_attributions"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_referral_attributions_public_id"),
        UniqueConstraint("referee_user_id", "family", name="uq_referral_attributions_referee_family"),
        Index("ix_referral_attributions_referrer", "referrer_user_id"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, default=uuid.uuid4)
    referee_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_referral_attributions_referee"), nullable=False
    )
    referee_identity_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("promo_identities.id", name="fk_referral_attributions_identity")
    )
    family: Mapped[str] = mapped_column(String(32), nullable=False)
    referrer_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_referral_attributions_referrer"), nullable=False
    )
    referral_code_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("referral_codes.id", name="fk_referral_attributions_code"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'attributed'"))
    attributed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _created_at()


class PromoEnrollment(Base):
    """Which campaign version's terms a referee accepted; pins the terms and the budget promise (Q117)."""

    __tablename__ = "promo_enrollments"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_promo_enrollments_public_id"),
        UniqueConstraint("attribution_id", "campaign_id", name="uq_promo_enrollments_attribution_campaign"),
        UniqueConstraint("referee_user_id", "idempotency_key", name="uq_promo_enrollments_idempotency"),
        ForeignKeyConstraint(
            ["campaign_version_id", "campaign_id"],
            ["promo_campaign_versions.id", "promo_campaign_versions.campaign_id"],
            name="fk_promo_enrollments_version",
        ),
        Index("uq_promo_enrollments_identity_family", "referee_identity_id", "family", unique=True,
              postgresql_where=text("status <> 'released'"), sqlite_where=text("status <> 'released'")),
        Index("uq_promo_enrollments_user_family", "referee_user_id", "family", unique=True,
              postgresql_where=text("status <> 'released'"), sqlite_where=text("status <> 'released'")),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, default=uuid.uuid4)
    attribution_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("referral_attributions.id", name="fk_promo_enrollments_attribution"), nullable=False
    )
    campaign_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("promo_campaigns.id", name="fk_promo_enrollments_campaign"), nullable=False
    )
    campaign_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    family: Mapped[str] = mapped_column(String(32), nullable=False)
    service_type: Mapped[str] = mapped_column(String(16), nullable=False)
    referrer_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_promo_enrollments_referrer"), nullable=False
    )
    referee_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_promo_enrollments_referee"), nullable=False
    )
    referee_identity_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("promo_identities.id", name="fk_promo_enrollments_identity"), nullable=False
    )
    terms_fingerprint: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    qualification_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'promised'"))
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _created_at()
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 0086 bookkeeping


# --- referral stage 3 (migration 20260923_0086) ------------------------------------------------------------------


class PromoQualificationEvent(Base):
    """Durable intake log: an event starts a check; the decision reads the source records (ADR-0023 §17 T1)."""

    __tablename__ = "promo_qualification_events"
    __table_args__ = (
        UniqueConstraint("dedup_key", name="uq_promo_qualification_events_dedup"),
        Index("ix_promo_qualification_events_pending", "id",
              postgresql_where=text("processed_at IS NULL"), sqlite_where=text("processed_at IS NULL")),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bookings.id", name="fk_promo_qualification_events_booking"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # service time at the source
    received_at: Mapped[datetime] = _created_at()  # arrival
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # worker time
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(String(200))
    dedup_key: Mapped[str] = mapped_column(String(200), nullable=False)


class PromoQualification(Base):
    """One decision record per (enrollment, milestone); converges under parallel workers (unique)."""

    __tablename__ = "promo_qualifications"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_promo_qualifications_public_id"),
        UniqueConstraint("enrollment_id", "milestone", name="uq_promo_qualifications_enrollment_milestone"),
        ForeignKeyConstraint(["cleared_review_id"], ["promo_reviews.id"], name="fk_promo_qualifications_cleared_review",
                             use_alter=True),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, default=uuid.uuid4)
    enrollment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("promo_enrollments.id", name="fk_promo_qualifications_enrollment"), nullable=False
    )
    milestone: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence_booking_ids: Mapped[Any] = mapped_column(JsonB, nullable=False, server_default=text("'[]'"))
    conditions_met_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    risk_ruleset_version: Mapped[str | None] = mapped_column(String(32))
    reason_codes: Mapped[Any] = mapped_column(JsonB, nullable=False, server_default=text("'[]'"))
    cleared_review_id: Mapped[int | None] = mapped_column(BigInteger)
    granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _created_at()


class PromoReview(Base):
    """A person's review: reason, evidence references (table + id), ruleset version, SLA, decision, times."""

    __tablename__ = "promo_reviews"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_promo_reviews_public_id"),
        UniqueConstraint("dedup_key", name="uq_promo_reviews_dedup"),
        Index("ix_promo_reviews_open", "status", "due_at",
              postgresql_where=text("status IN ('open', 'under_review')"),
              sqlite_where=text("status IN ('open', 'under_review')")),
        Index("ix_promo_reviews_enrollment", "enrollment_id"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(200), nullable=False)
    campaign_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("promo_campaigns.id", name="fk_promo_reviews_campaign")
    )
    attribution_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("referral_attributions.id", name="fk_promo_reviews_attribution")
    )
    enrollment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("promo_enrollments.id", name="fk_promo_reviews_enrollment")
    )
    qualification_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("promo_qualifications.id", name="fk_promo_reviews_qualification")
    )
    booking_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("bookings.id", name="fk_promo_reviews_booking"))
    reason_codes: Mapped[Any] = mapped_column(JsonB, nullable=False, server_default=text("'[]'"))
    evidence: Mapped[Any] = mapped_column(JsonB, nullable=False, server_default=text("'[]'"))
    risk_ruleset_version: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'open'"))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_to: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_promo_reviews_assigned_to")
    )
    decision_note: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_promo_reviews_decided_by")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _created_at()


class PromoClientFeatures(Base):
    """What a user's client last declared in ``X-Elchi-Client-Features`` (rendering capability, not authority)."""

    __tablename__ = "promo_client_features"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_promo_client_features_user"), primary_key=True, autoincrement=False
    )
    features: Mapped[Any] = mapped_column(JsonB, nullable=False, server_default=text("'[]'"))
    declared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 0089 (Q126): the login session (``sid``) of that declaration - used only to *detect* a change, never as evidence
    session_ref: Mapped[str | None] = mapped_column(String(64))


class PromoConsent(Base):
    """The client's consent to spend passenger bonus on exactly one proposal version or amendment (Q104)."""

    __tablename__ = "promo_consents"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_promo_consents_public_id"),
        Index("uq_promo_consents_active_version", "proposal_version_id", unique=True,
              postgresql_where=text("status = 'active' AND proposal_version_id IS NOT NULL"),
              sqlite_where=text("status = 'active' AND proposal_version_id IS NOT NULL")),
        Index("uq_promo_consents_active_amendment", "amendment_id", unique=True,
              postgresql_where=text("status = 'active' AND amendment_id IS NOT NULL"),
              sqlite_where=text("status = 'active' AND amendment_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, default=uuid.uuid4)
    client_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_promo_consents_client"), nullable=False
    )
    proposal_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("proposal_versions.id", name="fk_promo_consents_version")
    )
    amendment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("booking_amendments.id", name="fk_promo_consents_amendment")
    )
    booking_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("bookings.id", name="fk_promo_consents_booking"))
    service_type: Mapped[str] = mapped_column(String(16), nullable=False)
    contract_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    fare_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    passenger_bonus_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cash_due_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    quote_fingerprint: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    client_features: Mapped[Any] = mapped_column(JsonB, nullable=False, server_default=text("'[]'"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'active'"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()
    # 0089: the one campaign that funds P (Q123) and the login session that gave the consent (Q126)
    passenger_campaign_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("promo_campaigns.id", name="fk_promo_consents_passenger_campaign")
    )
    session_ref: Mapped[str | None] = mapped_column(String(64))


class PromoBookingTerms(Base):
    """Immutable financial snapshot of a promo booking; ``seq`` 1 at accept, one more per accepted amendment."""

    __tablename__ = "promo_booking_terms"
    __table_args__ = (UniqueConstraint("booking_id", "seq", name="uq_promo_booking_terms_booking_seq"),)

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bookings.id", name="fk_promo_booking_terms_booking"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    amendment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("booking_amendments.id", name="fk_promo_booking_terms_amendment")
    )
    consent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("promo_consents.id", name="fk_promo_booking_terms_consent")
    )
    contract_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default=text("'UZS'"))
    fare_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fee_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    base_commission_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    passenger_bonus_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    driver_credit_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cash_due_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    net_commission_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    variable_cost_minor: Mapped[int | None] = mapped_column(BigInteger)
    min_margin_minor: Mapped[int | None] = mapped_column(BigInteger)
    quote_fingerprint: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    # 0089 (Q123): the single campaign behind P and behind H, and the approved cost basis when they differ
    passenger_campaign_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("promo_campaigns.id", name="fk_promo_booking_terms_passenger_campaign")
    )
    driver_campaign_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("promo_campaigns.id", name="fk_promo_booking_terms_driver_campaign")
    )
    combination_cost_basis: Mapped[str | None] = mapped_column(String(16))


class PromoCampaignCombination(Base):
    """Q123: an explicit approval that two campaigns may fund one booking together (P from one, H from the other).

    Unordered pair stored low < high; one active row per pair; ``active -> revoked`` only (0089 trigger)."""

    __tablename__ = "promo_campaign_combinations"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_promo_campaign_combinations_public_id"),
        Index("uq_promo_campaign_combinations_active", "campaign_low_id", "campaign_high_id", unique=True,
              postgresql_where=text("status = 'active'"), sqlite_where=text("status = 'active'")),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, default=uuid.uuid4)
    campaign_low_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("promo_campaigns.id", name="fk_promo_campaign_combinations_low"), nullable=False
    )
    campaign_high_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("promo_campaigns.id", name="fk_promo_campaign_combinations_high"), nullable=False
    )
    cost_basis: Mapped[str] = mapped_column(String(16), nullable=False)  # shared | additive
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'active'"))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_promo_campaign_combinations_created_by"), nullable=False
    )
    created_at: Mapped[datetime] = _created_at()
    revoked_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", name="fk_promo_campaign_combinations_revoked_by")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class PromoPartyReadiness(Base):
    """Q126: the passive party's readiness for one proposal version or amendment - bound to that subject, the login
    session that declared it and an expiry. Never open-ended; a new confirmation supersedes it (0089 trigger)."""

    __tablename__ = "promo_party_readiness"
    __table_args__ = (
        Index("uq_promo_party_readiness_version", "proposal_version_id", "user_id", unique=True,
              postgresql_where=text("status = 'active' AND proposal_version_id IS NOT NULL"),
              sqlite_where=text("status = 'active' AND proposal_version_id IS NOT NULL")),
        Index("uq_promo_party_readiness_amendment", "amendment_id", "user_id", unique=True,
              postgresql_where=text("status = 'active' AND amendment_id IS NOT NULL"),
              sqlite_where=text("status = 'active' AND amendment_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", name="fk_promo_party_readiness_user"),
                                         nullable=False)
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    proposal_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("proposal_versions.id", name="fk_promo_party_readiness_version")
    )
    amendment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("booking_amendments.id", name="fk_promo_party_readiness_amendment")
    )
    session_ref: Mapped[str | None] = mapped_column(String(64))
    features: Mapped[Any] = mapped_column(JsonB, nullable=False, server_default=text("'[]'"))
    acknowledged: Mapped[Any | None] = mapped_column(JsonB)  # the driver's acknowledged amounts (amendments)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'active'"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _created_at()


class PromoRateEvent(Base):
    """One counted request of an abuse-prone referral endpoint (0088). ``key_hash`` = HMAC of the source, never clear."""

    __tablename__ = "promo_rate_events"
    __table_args__ = (Index("ix_promo_rate_events_window", "action", "key_hash", "created_at"),)

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    key_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = _created_at()
