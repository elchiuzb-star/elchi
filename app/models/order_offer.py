from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin


class OrderOffer(TimestampMixin, Base):
    __tablename__ = "order_offers"
    __table_args__ = (
        UniqueConstraint("order_id", "driver_id", name="uq_order_offers_order_driver"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True, nullable=False)
    driver_id: Mapped[int] = mapped_column(ForeignKey("driver_profiles.id"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="shown", nullable=False)
    result: Mapped[str] = mapped_column(String(32), default="shown", nullable=False)
    shown_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
