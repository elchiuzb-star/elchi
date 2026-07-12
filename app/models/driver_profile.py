from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin


class DriverProfile(TimestampMixin, Base):
    __tablename__ = "driver_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    full_name: Mapped[str | None] = mapped_column(String(255))
    car_model: Mapped[str | None] = mapped_column(String(255))
    plate_number: Mapped[str | None] = mapped_column(String(32), unique=True)
    plate_number_normalized: Mapped[str | None] = mapped_column(String(32), index=True)
    car_color: Mapped[str | None] = mapped_column(String(64))
    verification_status: Mapped[str] = mapped_column(
        String(32),
        default="new",
        nullable=False,
    )
    is_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rating_avg: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=0, nullable=False)
    total_orders: Mapped[int] = mapped_column(default=0, nullable=False)
    completed_orders: Mapped[int] = mapped_column(default=0, nullable=False)
    cancelled_orders: Mapped[int] = mapped_column(default=0, nullable=False)
    dispute_count: Mapped[int] = mapped_column(default=0, nullable=False)

    user: Mapped["User"] = relationship(back_populates="driver_profile")
    documents: Mapped[list["DriverDocument"]] = relationship(back_populates="driver")
    routes: Mapped[list["DriverRoute"]] = relationship(back_populates="driver")
