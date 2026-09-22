import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("phone", name="uq_users_phone"),
        # Stage-2 opaque id (ADR-0002, migration 20260913_0032). Not exposed by v1 responses.
        UniqueConstraint("public_id", name="uq_users_public_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Python default keeps SQLite create_all and ORM inserts working; PostgreSQL also has
    # DEFAULT gen_random_uuid() from 0032 for raw SQL inserts.
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, default=uuid.uuid4)
    phone: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    # Staff sign in with username + password; clients and drivers use SMS OTP
    # and leave both of these null.
    username: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    is_phone_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    client_profile: Mapped["ClientProfile | None"] = relationship(
        back_populates="user",
        uselist=False,
    )
    driver_profile: Mapped["DriverProfile | None"] = relationship(
        back_populates="user",
        uselist=False,
    )
