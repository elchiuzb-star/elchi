from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin


class Order(TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("order_number", name="uq_orders_order_number"),
        CheckConstraint("from_city_id <> to_city_id", name="ck_orders_distinct_cities"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_number: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    client_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    from_city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"), index=True, nullable=False)
    to_city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"), index=True, nullable=False)
    from_district_id: Mapped[int | None] = mapped_column(ForeignKey("districts.id"), index=True)
    to_district_id: Mapped[int | None] = mapped_column(ForeignKey("districts.id"), index=True)
    pickup_address: Mapped[str] = mapped_column(String(1024), nullable=False)
    dropoff_address: Mapped[str] = mapped_column(String(1024), nullable=False)
    pickup_lat: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    pickup_lng: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    dropoff_lat: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    dropoff_lng: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    sender_phone: Mapped[str] = mapped_column(String(32), nullable=False)
    receiver_phone: Mapped[str] = mapped_column(String(32), nullable=False)
    cargo_photo_url: Mapped[str | None] = mapped_column(String(1024))
    cargo_type: Mapped[str | None] = mapped_column(String(32))
    comment: Mapped[str | None] = mapped_column(Text)
    suggested_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    client_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    final_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    system_fee_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    system_fee: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    driver_income: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    payment_method: Mapped[str] = mapped_column(String(32), default="cash", nullable=False)
    payment_status: Mapped[str] = mapped_column(String(32), default="unpaid", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True, nullable=False)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    cancelled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    assigned_driver_id: Mapped[int | None] = mapped_column(ForeignKey("driver_profiles.id"), index=True)
    accepted_bid_id: Mapped[int | None] = mapped_column(
        ForeignKey("bids.id", use_alter=True, name="fk_orders_accepted_bid_id_bids"),
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    in_transit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
