from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin


class Bid(TimestampMixin, Base):
    __tablename__ = "bids"
    __table_args__ = (
        UniqueConstraint("order_id", "driver_id", name="uq_bids_order_driver"),
        CheckConstraint("price > 0", name="ck_bids_price_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True, nullable=False)
    driver_id: Mapped[int] = mapped_column(ForeignKey("driver_profiles.id"), index=True, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    price_update_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
