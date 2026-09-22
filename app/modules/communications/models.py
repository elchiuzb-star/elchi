"""ORM mapping for the communications tables created by migration 20260916_0059 (A7).

The migration is the source of truth (CHECKs, guard trigger ``chat_message_immutable``, partial indexes).
These classes mirror columns, unique constraints and indexes so the ORM drift check stays empty.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text as sa_text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.modules.platform.models import BigIdentity, JsonB

COMMUNICATIONS_TABLES: tuple[str, ...] = (
    "chat_threads",
    "chat_messages",
    "device_tokens",
    "device_account_links",
    "notification_deliveries",
    "notification_dedup",
)

PENDING_PUSH_PREDICATE = "channel <> 'in_app' AND status IN ('pending', 'failed')"
INBOX_PREDICATE = "channel = 'in_app' AND status = 'sent'"


class ChatThread(Base):
    __tablename__ = "chat_threads"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_chat_threads_public_id"),
        UniqueConstraint("proposal_thread_id", name="uq_chat_threads_proposal_thread_id"),
        UniqueConstraint("booking_id", name="uq_chat_threads_booking_id"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    proposal_thread_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("proposal_threads.id", name="fk_chat_threads_proposal_thread_id")
    )
    booking_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("bookings.id", name="fk_chat_threads_booking_id"))
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_chat_messages_public_id"),
        Index("ix_chat_messages_thread_id", "thread_id", "id"),
        Index("ix_chat_messages_author_thread_created", "author_user_id", "thread_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    thread_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chat_threads.id", name="fk_chat_messages_thread_id"), nullable=False
    )
    author_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_chat_messages_author_user_id"), nullable=False
    )
    author_side: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str | None] = mapped_column(Text)
    quick_reply_code: Mapped[str | None] = mapped_column(String(32))
    attachment_file_id: Mapped[int | None] = mapped_column(BigInteger)
    contact_filter_categories: Mapped[dict[str, Any]] = mapped_column(JsonB, nullable=False, server_default=sa_text("'{}'"))
    contact_filter_version: Mapped[str | None] = mapped_column(String(32))
    moderation_status: Mapped[str] = mapped_column(String(24), nullable=False, server_default=sa_text("'visible'"))
    moderated_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", name="fk_chat_messages_moderated_by"))
    moderated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DeviceToken(Base):
    """Push device registration.

    ``token_hash`` is the lookup key and always present. ``token_cipher`` holds the registration token itself,
    sealed with AES-256-GCM (ADR-0022) because FCM needs it to deliver; it is NULL for rows registered before
    migration 0073 and for any environment that never received a raw token. Nothing here is ever logged.
    """

    __tablename__ = "device_tokens"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_device_tokens_public_id"),
        UniqueConstraint("platform", "token_hash", name="uq_device_tokens_platform_token_hash"),
        Index("ix_device_tokens_user_id", "user_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", name="fk_device_tokens_user_id"), nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    #: ADR-0022: sealed registration token (nonce || ciphertext), AAD = this row's public id. NULL = cannot push.
    #: The comment is declared here as well so the ORM matches what 0073 wrote (schema-drift gate).
    token_cipher: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        comment=(
            "ADR-0022: AES-256-GCM sealed push registration token (nonce || ciphertext), AAD = device public "
            "id. NULL for devices registered before 0073 - they re-register before they can be pushed to."
        ),
    )
    token_key_version: Mapped[int | None] = mapped_column(SmallInteger)
    app_version: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationDelivery(Base):
    """One copy of one outbox event for one user on one channel; ``channel = in_app`` rows are the v2 inbox."""

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_notification_deliveries_public_id"),
        UniqueConstraint("event_id", "user_id", "channel", name="uq_notification_deliveries_event_user_channel"),
        Index(
            "ix_notification_deliveries_inbox",
            "user_id",
            "id",
            postgresql_where=sa_text(INBOX_PREDICATE),
            sqlite_where=sa_text(INBOX_PREDICATE),
        ),
        Index(
            "ix_notification_deliveries_push_due",
            "next_attempt_at",
            postgresql_where=sa_text(PENDING_PUSH_PREDICATE),
            sqlite_where=sa_text(PENDING_PUSH_PREDICATE),
        ),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_public_id: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_notification_deliveries_user_id"), nullable=False
    )
    audience: Mapped[str] = mapped_column(String(24), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonB, nullable=False, server_default=sa_text("'{}'"))
    link: Mapped[str | None] = mapped_column(String(255))
    skip_reason: Mapped[str | None] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class NotificationDedup(Base):
    """``NOTIFICATION_DEDUP_WINDOW`` buckets: one push per (user, dedup_key, window_start) (§6.6)."""

    __tablename__ = "notification_dedup"
    __table_args__ = (
        UniqueConstraint("user_id", "dedup_key", "window_start", name="uq_notification_dedup_user_key_window"),
        Index("ix_notification_dedup_window_start", "window_start"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", name="fk_notification_dedup_user_id"), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(255), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DeviceAccountLink(Base):
    """§17.3: which accounts one push device has belonged to (append-only; migration 20260917_0068).

    ``device_tokens`` keeps only the current owner, so a device moving between accounts left no trace. A12 reads
    this history through ``communications.service.device_account_groups`` to raise a *signal for review* - never
    an automatic block.
    """

    __tablename__ = "device_account_links"
    __table_args__ = (
        UniqueConstraint("platform", "token_hash", "user_id", name="uq_device_account_links"),
        Index("ix_device_account_links_user", "user_id", "last_seen_at"),
        {
            "comment": (
                "§17.3: which accounts a push device has belonged to. Append-only history behind the "
                "shared-device signal; no raw token, no payload, no location."
            )
        },
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="device_account_links_user_id_fkey"), nullable=False
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
