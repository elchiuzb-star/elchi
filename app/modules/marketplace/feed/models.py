"""ORM mapping for the saved-search tables created by migration 20260916_0061 (A5).

The migration is the source of truth: CHECKs (one reference per end, window, quantity) and the
``saved_search_limit`` guard trigger live only in the database.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
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

from app.db.base import Base
import app.modules.geo.models  # noqa: E402,F401  (FK targets: corridor_stops, regions)
import app.modules.marketplace.models  # noqa: E402,F401  (FK target: listings)

BigIdentity = BigInteger().with_variant(Integer(), "sqlite")

FEED_TABLES: tuple[str, ...] = ("saved_searches", "saved_search_notifications", "feed_search_events")

LIVE_PREDICATE = "deleted_at IS NULL"
NOTIFY_PREDICATE = "deleted_at IS NULL AND notify"


class SavedSearch(Base):
    __tablename__ = "saved_searches"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_saved_searches_public_id"),
        Index(
            "ix_saved_searches_user_created",
            "user_id",
            "created_at",
            "id",
            postgresql_where=text(LIVE_PREDICATE),
            sqlite_where=text(LIVE_PREDICATE),
        ),
        Index(
            "ix_saved_searches_notify_match",
            "service_type",
            "side",
            "time_window_end",
            postgresql_where=text(NOTIFY_PREDICATE),
            sqlite_where=text(NOTIFY_PREDICATE),
        ),
        Index(
            "ix_saved_searches_origin_district",
            "origin_district_id",
            postgresql_where=text("origin_district_id IS NOT NULL"),
            sqlite_where=text("origin_district_id IS NOT NULL"),
        ),
        Index(
            "ix_saved_searches_destination_district",
            "destination_district_id",
            postgresql_where=text("destination_district_id IS NOT NULL"),
            sqlite_where=text("destination_district_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", name="fk_saved_searches_user_id"), nullable=False)
    service_type: Mapped[str] = mapped_column(String(16), nullable=False)
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    origin_stop_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("corridor_stops.id", name="fk_saved_searches_origin_stop_id")
    )
    origin_region_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("regions.id", name="fk_saved_searches_origin_region_id")
    )
    # Wave 10 (0075): a district end, alongside the stop and the region. The DB CHECK still allows exactly one.
    origin_district_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("geo_districts.id", name="fk_saved_searches_origin_district_id")
    )
    destination_stop_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("corridor_stops.id", name="fk_saved_searches_destination_stop_id")
    )
    destination_region_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("regions.id", name="fk_saved_searches_destination_region_id")
    )
    destination_district_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("geo_districts.id", name="fk_saved_searches_destination_district_id")
    )
    time_window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    time_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    notify: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SavedSearchNotification(Base):
    """One ``saved_search.matched`` per (saved search, listing) (§6.6: no duplicate push)."""

    __tablename__ = "saved_search_notifications"
    __table_args__ = (
        UniqueConstraint("saved_search_id", "listing_id", name="uq_saved_search_notifications_search_listing"),
        Index("ix_saved_search_notifications_listing_id", "listing_id"),
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    saved_search_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("saved_searches.id", name="fk_saved_search_notifications_saved_search_id"),
        nullable=False,
    )
    listing_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("listings.id", name="fk_saved_search_notifications_listing_id"), nullable=False
    )
    notified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class FeedSearchEvent(Base):
    """§20.4 ``search_with_match_rate`` (migration 20260917_0069).

    One append-only row per feed search. It answers a single question - "did this search find anything?" - and
    deliberately stores no user id, no stop ids and no filter values, so the KPI never turns into a personal
    search history (§17.7). The worker deletes rows past the retention window.
    """

    __tablename__ = "feed_search_events"
    __table_args__ = (
        Index("ix_feed_search_events_day", "occurred_at", "corridor_id"),
        {
            "comment": (
                "§20.4 search_with_match_rate. Append-only counter rows: no user id, no stop ids, no filter "
                "values - only service, side, corridor and whether the search found something."
            )
        },
    )

    id: Mapped[int] = mapped_column(BigIdentity, Identity(always=True), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    service_type: Mapped[str] = mapped_column(String(16), nullable=False)
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    corridor_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("service_corridors.id", name="feed_search_events_corridor_id_fkey")
    )
    matched: Mapped[bool] = mapped_column(Boolean, nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
