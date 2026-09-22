"""ORM mapping for wallet tables (migrations 20260913_0036 and 20260913_0041).

Migrations own CHECK/EXCLUDE constraints and triggers; these classes mirror
columns, unique constraints and indexes (ORM drift check) and stay SQLite-creatable.
``commission_policies.scope_corridor_id`` references ``service_corridors`` in the DB
only: declaring that FK here would break ``create_all`` wherever the geo models are
not imported (reported to A0a/A0b).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    JSON,
    BigInteger,
    Boolean,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
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

try:  # commission_policies.scope_corridor_id -> service_corridors (A2); FK needs the table in metadata.
    import app.modules.geo.models  # noqa: F401
except ImportError:  # pragma: no cover - geo module always present from wave 1
    pass

BigIdentity = BigInteger().with_variant(Integer(), "sqlite")
JsonB = JSONB().with_variant(JSON(), "sqlite")

SCOPE_KEY_SQL = "COALESCE(CAST(scope_corridor_id AS TEXT), '*') || ':' || COALESCE(scope_service_type, '*')"


class CommissionPolicy(Base):
    __tablename__ = "commission_policies"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_commission_policies_public_id"),
        Index("ix_commission_policies_active_lookup", "kind", "scope_key", "effective_from"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_corridor_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("service_corridors.id", name="fk_commission_policies_scope_corridor")
    )
    scope_service_type: Mapped[str | None] = mapped_column(String(16))
    scope_key: Mapped[str] = mapped_column(String(64), Computed(SCOPE_KEY_SQL, persisted=True))
    fee_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    campaign_name: Mapped[str | None] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    ended_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    ended_reason: Mapped[str | None] = mapped_column(Text)
    # Decision 28 (0042): a super_admin confirms the migration-seeded rate once before production use.
    confirmed_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class LedgerAccount(Base):
    __tablename__ = "ledger_accounts"
    __table_args__ = (UniqueConstraint("code", "currency", name="uq_ledger_accounts_code_currency"),)

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    owner_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default=text("'UZS'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class WalletAccount(Base):
    __tablename__ = "wallet_accounts"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_wallet_accounts_public_id"),
        UniqueConstraint("driver_user_id", "currency", name="uq_wallet_accounts_driver_currency"),
        UniqueConstraint("ledger_account_id", name="uq_wallet_accounts_ledger_account"),
        Index(
            "ix_wallet_accounts_test_overdraft",
            "id",
            postgresql_where=text("test_overdraft_allowed"),
            sqlite_where=text("test_overdraft_allowed"),
        ),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, default=uuid.uuid4)
    driver_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    ledger_account_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("ledger_accounts.id"), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default=text("'UZS'"))
    posted_balance_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    held_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    test_overdraft_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class LedgerTransaction(Base):
    __tablename__ = "ledger_transactions"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_ledger_transactions_public_id"),
        UniqueConstraint("reference_kind", "reference_key", name="uq_ledger_transactions_reference"),
        Index("ix_ledger_transactions_reversal_of_id", "reversal_of_id"),
        Index("ix_ledger_transactions_wallet_id", "wallet_id", "id"),
        Index("ix_ledger_transactions_source", "source_type", "source_id"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, default=uuid.uuid4)
    reference_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_key: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    reversal_of_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ledger_transactions.id"))
    wallet_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("wallet_accounts.id"))
    # 0055: FK to bookings (NOT VALID + VALIDATE in the migration).
    booking_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("bookings.id", name="fk_ledger_transactions_booking_id")
    )
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    second_approver_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    evidence: Mapped[dict[str, Any]] = mapped_column(JsonB, nullable=False)
    # Q55 (0052): the one business source of this posting, validated at COMMIT by a DB trigger.
    source_type: Mapped[str | None] = mapped_column(String(32))
    source_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        Index("ix_ledger_entries_transaction_id", "transaction_id"),
        Index("ix_ledger_entries_account_id", "account_id", "id"),
        Index(
            "uq_ledger_entries_account_seq",
            "account_id",
            "account_seq",
            unique=True,
            postgresql_where=text("account_seq IS NOT NULL"),
            sqlite_where=text("account_seq IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    transaction_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("ledger_transactions.id"), nullable=False)
    account_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("ledger_accounts.id"), nullable=False)
    direction: Mapped[str] = mapped_column(String(6), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Wave 1.6 N1 (0047): assigned by the database for driver-liability entries only; immutable.
    account_seq: Mapped[int | None] = mapped_column(BigInteger)
    running_balance_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default=text("'UZS'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class WalletHold(Base):
    __tablename__ = "wallet_holds"
    __table_args__ = (
        UniqueConstraint("booking_id", "charge_kind", name="uq_wallet_holds_booking_charge"),
        Index("ix_wallet_holds_wallet_status", "wallet_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    wallet_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("wallet_accounts.id"), nullable=False)
    # 0055: FK to bookings (NOT VALID + VALIDATE in the migration).
    booking_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bookings.id", name="fk_wallet_holds_booking_id"), nullable=False
    )
    booking_public_id: Mapped[str | None] = mapped_column(String(64))
    charge_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    fee_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default=text("'UZS'"))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    captured_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    reversed_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    capture_transaction_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ledger_transactions.id"))
    escalate_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TopupRequest(Base):
    __tablename__ = "topup_requests"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_topup_requests_public_id"),
        Index(
            "uq_topup_requests_source_reference",
            "source_type",
            "source_reference",
            unique=True,
            postgresql_where=text("status IN ('awaiting_second_approval', 'approved')"),
            sqlite_where=text("status IN ('awaiting_second_approval', 'approved')"),
        ),
        Index("ix_topup_requests_driver", "driver_user_id", "id"),
        Index("ix_topup_requests_status", "status", "id"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, default=uuid.uuid4)
    driver_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    wallet_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("wallet_accounts.id"), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default=text("'UZS'"))
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    payer_reference: Mapped[str | None] = mapped_column(String(128))
    evidence_file_id: Mapped[str | None] = mapped_column(String(128))
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source_type: Mapped[str | None] = mapped_column(String(32))
    source_reference: Mapped[str | None] = mapped_column(String(128))
    received_amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_approver_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    second_approver_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    rejected_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    reject_reason: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ledger_transaction_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ledger_transactions.id"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class LedgerAdjustmentRequest(Base):
    """Two-person rule for large manual adjustments (Q17). Small ones post immediately."""

    __tablename__ = "ledger_adjustment_requests"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_ledger_adjustment_requests_public_id"),
        Index("ix_ledger_adjustment_requests_status", "status", "id"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, default=uuid.uuid4)
    wallet_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("wallet_accounts.id"), nullable=False)
    direction: Mapped[str] = mapped_column(String(6), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default=text("'UZS'"))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JsonB, nullable=False)
    booking_id: Mapped[int | None] = mapped_column(BigInteger)
    reversal_of_transaction_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ledger_transactions.id"))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    approved_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    rejected_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"))
    reject_reason: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ledger_transaction_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ledger_transactions.id"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class LedgerAccountBalance(Base):
    """Running balance of a driver liability account, written only by a DB trigger (0042, BR #8)."""

    __tablename__ = "ledger_account_balances"

    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ledger_accounts.id"), primary_key=True, autoincrement=False
    )
    balance_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    last_account_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ReconciliationRun(Base):
    __tablename__ = "reconciliation_runs"
    __table_args__ = (UniqueConstraint("run_date", name="uq_reconciliation_runs_run_date"),)

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    wallets_checked: Mapped[int] = mapped_column(Integer, nullable=False)
    mismatch_count: Mapped[int] = mapped_column(Integer, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JsonB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# FK target ``bookings`` (0055) must be in the metadata for ``create_all``/mapper configuration. Imported at the
# bottom: ``app.modules.bookings.models`` imports this module for ``commission_policies`` (cycle-safe here).
try:
    import app.modules.bookings.models  # noqa: E402,F401
except ImportError:  # pragma: no cover - bookings ships in wave 2
    pass
