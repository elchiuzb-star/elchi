"""ORM mapping for identity tables created by migration 20260913_0032.

The migration is the source of truth (CHECKs, the Q3 trigger, partial indexes,
the users.public_id column). These classes mirror columns, unique constraints and
indexes so the ORM drift check stays empty, and stay SQLite-creatable because the
legacy suite calls ``Base.metadata.create_all``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CHAR,
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.modules.platform.models import JsonB

BigIdentity = BigInteger().with_variant(Integer(), "sqlite")


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role", name="uq_user_roles_user_role"),)

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_user_roles_user_id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'active'"))
    granted_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", name="fk_user_roles_granted_by"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DriverEligibilityBlock(Base):
    __tablename__ = "driver_eligibility_blocks"
    __table_args__ = (
        Index(
            "uq_driver_eligibility_blocks_active",
            "driver_user_id",
            unique=True,
            postgresql_where=text("lifted_at IS NULL"),
            sqlite_where=text("lifted_at IS NULL"),
        ),
        Index("ix_driver_eligibility_blocks_driver_user_id", "driver_user_id"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    driver_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_driver_eligibility_blocks_driver_user_id"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    blocked_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_driver_eligibility_blocks_blocked_by"), nullable=False
    )
    blocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    lifted_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_driver_eligibility_blocks_lifted_by")
    )
    lifted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lift_reason: Mapped[str | None] = mapped_column(Text)


class DriverDocumentValidity(Base):
    __tablename__ = "driver_document_validity"
    __table_args__ = (
        UniqueConstraint("driver_document_id", name="uq_driver_document_validity_driver_document_id"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    driver_document_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("driver_documents.id", name="fk_driver_document_validity_driver_document_id", ondelete="CASCADE"),
        nullable=False,
    )
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_driver_document_validity_verified_by"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)



class StaffMfaFactor(Base):
    """ADR-0021 staff second factor (migration 20260917_0074).

    The TOTP secret lives here sealed with AES-GCM and is never returned by any read path. ``activated_by``
    can never equal ``user_id`` - the database enforces it, because "I approved my own second factor" is the
    exact failure MFA is supposed to prevent.
    """

    __tablename__ = "staff_mfa_factors"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_staff_mfa_factors_public_id"),
        Index("uq_staff_mfa_factors_active_user", "user_id", unique=True,
              postgresql_where=text("status = 'active'"), sqlite_where=text("status = 'active'")),
        {"comment": (
            "ADR-0021: staff second factor. The secret is sealed (AES-GCM), never stored or logged in the "
            "clear; activation needs a different super_admin (ck_staff_mfa_factors_two_person)."
        )},
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[str] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="staff_mfa_factors_user_id_fkey"), nullable=False
    )
    factor_type: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'totp'"))
    secret_cipher: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    secret_key_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("1"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'pending'"))
    #: Highest TOTP time step already accepted: the same code cannot be replayed inside its own window.
    last_counter: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", name="staff_mfa_factors_activated_by_fkey")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class StaffMfaRecoveryCode(Base):
    """One-time recovery code (SHA-256 only). Restores enrollment; never a financial approval."""

    __tablename__ = "staff_mfa_recovery_codes"
    __table_args__ = (
        UniqueConstraint("code_hash", name="uq_staff_mfa_recovery_code_hash"),
        Index("ix_staff_mfa_recovery_codes_user", "user_id", "id"),
        {"comment": (
            "ADR-0021: SHA-256 of one-time recovery codes. A code restores the ability to enroll a factor; it "
            "is never a financial approval and never bypasses the two-person money rule."
        )},
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="staff_mfa_recovery_codes_user_id_fkey"), nullable=False
    )
    code_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StaffMfaEvent(Base):
    """Append-only MFA trail (DB trigger refuses UPDATE/DELETE). Carries no secret and no code."""

    __tablename__ = "staff_mfa_events"
    __table_args__ = (
        Index("ix_staff_mfa_events_user", "user_id", "id"),
        {"comment": "ADR-0021: append-only MFA audit trail, no secrets."},
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="staff_mfa_events_user_id_fkey"), nullable=False
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", name="staff_mfa_events_actor_user_id_fkey")
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[dict] = mapped_column(JsonB, nullable=False, server_default=text("'{}'"))  # portable; the migration casts to jsonb
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# users.public_id is declared on app.models.User (integration pass 2); the former
# metadata-only column patch was removed.


# Core-only projection of the legacy ``users`` table for ``public_id`` (added by 0032).
# Deliberately NOT on Base.metadata: ``app.models.User`` is v1-owned and must not change here.
_legacy_metadata = MetaData()
users_identity = Table(
    "users",
    _legacy_metadata,
    Column("id", Integer, primary_key=True),
    Column("public_id", Uuid, nullable=False),
    Column("phone", String(32)),
    Column("full_name", String(255)),
    Column("role", String(32)),
    Column("status", String(32)),
    Column("created_at", DateTime(timezone=True)),
)
