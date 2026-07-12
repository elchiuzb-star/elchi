from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Numeric, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin


class RouteTariff(TimestampMixin, Base):
    __tablename__ = "route_tariffs"
    __table_args__ = (
        CheckConstraint("from_city_id <> to_city_id", name="ck_route_tariffs_distinct_cities"),
        CheckConstraint("suggested_price >= 0", name="ck_route_tariffs_suggested_price_nonnegative"),
        CheckConstraint("min_price IS NULL OR min_price >= 0", name="ck_route_tariffs_min_price_nonnegative"),
        CheckConstraint("max_price IS NULL OR max_price >= 0", name="ck_route_tariffs_max_price_nonnegative"),
        CheckConstraint(
            "min_price IS NULL OR min_price <= suggested_price",
            name="ck_route_tariffs_min_lte_suggested",
        ),
        CheckConstraint(
            "max_price IS NULL OR suggested_price <= max_price",
            name="ck_route_tariffs_suggested_lte_max",
        ),
        Index(
            "uq_route_tariffs_active_route",
            "from_city_id",
            "to_city_id",
            unique=True,
            postgresql_where=text("is_active = true"),
            sqlite_where=text("is_active = 1"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    from_city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"), index=True, nullable=False)
    to_city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"), index=True, nullable=False)
    suggested_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    min_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    max_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)
