from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin


class District(TimestampMixin, Base):
    __tablename__ = "districts"
    __table_args__ = (
        Index("ix_districts_city_lower_name_uz", "city_id", text("lower(name_uz)"), unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"), index=True, nullable=False)
    name_uz: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    name_ru: Mapped[str | None] = mapped_column(String(120), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    center_lat: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    center_lng: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
