"""ORM mapping for the operations tables created by migration 20260916_0064 (A13, wave 4).

The migration is the source of truth: CHECKs and the ``share_links_guard`` trigger live only in the database.
Only the SHA-256 of a share token is stored (ADR-0018); the token itself is shown once and never persisted.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CHAR,
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

import app.modules.geo.models  # noqa: F401  (FK target: service_corridors)
import app.modules.marketplace.models  # noqa: F401  (FK target: listings)
from app.db.base import Base

BigIdentity = BigInteger().with_variant(Integer(), "sqlite")

OPERATIONS_TABLES: tuple[str, ...] = ("share_links", "kpi_daily")
SHARE_LINK_TOKEN_UNIQUE = "uq_share_links_token_hash"
KPI_DAILY_UNIQUE = "uq_kpi_daily_day_metric_corridor"


class ShareLink(Base):
    """O1-O3 (§20.2): a public, PII-free page for one listing behind a secret token."""

    __tablename__ = "share_links"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_share_links_public_id"),
        UniqueConstraint("token_hash", name=SHARE_LINK_TOKEN_UNIQUE),
        Index("ix_share_links_listing_active", "listing_id", "id", postgresql_where=text("revoked_at IS NULL")),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    listing_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("listings.id", name="fk_share_links_listing_id"), nullable=False
    )
    created_by_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", name="fk_share_links_created_by_user_id"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class KpiDaily(Base):
    """O5 (§20.4): one metric per day (and optionally per corridor) as a count pair, never as a stored ratio."""

    __tablename__ = "kpi_daily"
    __table_args__ = (
        UniqueConstraint("day", "metric", "corridor_id", name=KPI_DAILY_UNIQUE, postgresql_nulls_not_distinct=True),
        Index("ix_kpi_daily_day_metric", "day", "metric"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    metric: Mapped[str] = mapped_column(String(48), nullable=False)
    corridor_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("service_corridors.id", name="fk_kpi_daily_corridor_id")
    )
    numerator: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    denominator: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
