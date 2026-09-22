from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin


class RefreshSession(TimestampMixin, Base):
    __tablename__ = "refresh_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: §17.6 (0072): why the session ended - "logout", "rotated", "admin_revoke", "account_deleted".
    #: NULL while the session is live, and on rows revoked before 0072 (then treated as ended, fail closed).
    revoked_reason: Mapped[str | None] = mapped_column(
        String(32),
        comment=(
            "§17.6: why the session ended. NULL on a live session, and on rows revoked before 0072 "
            "(treated as ended). 'rotated' means a successor session exists."
        ),
    )
    user_agent: Mapped[str | None] = mapped_column(String(512))
    ip_address: Mapped[str | None] = mapped_column(String(64))

    user: Mapped["User"] = relationship()
