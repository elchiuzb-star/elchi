from sqlalchemy import Boolean, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin


class City(TimestampMixin, Base):
    __tablename__ = "cities"
    __table_args__ = (
        UniqueConstraint("name_uz", name="uq_cities_name_uz"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    name_uz: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    name_ru: Mapped[str | None] = mapped_column(String(120), index=True)
    region: Mapped[str | None] = mapped_column(String(120), index=True)
    type: Mapped[str] = mapped_column(String(32), default="region", nullable=False)
    requires_district: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
