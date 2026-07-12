from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin


class DriverRoute(TimestampMixin, Base):
    __tablename__ = "driver_routes"
    __table_args__ = (
        CheckConstraint("from_city_id <> to_city_id", name="ck_driver_routes_distinct_cities"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("driver_profiles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    from_city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"), index=True, nullable=False)
    to_city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"), index=True, nullable=False)
    from_district_id: Mapped[int | None] = mapped_column(ForeignKey("districts.id"), index=True)
    to_district_id: Mapped[int | None] = mapped_column(ForeignKey("districts.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="available", nullable=False)

    driver: Mapped["DriverProfile"] = relationship(back_populates="routes")
