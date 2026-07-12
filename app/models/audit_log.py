from sqlalchemy import ForeignKey, JSON, Integer, String, event
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    entity_id: Mapped[int | None] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    details: Mapped[dict | None] = mapped_column(JSON)


def _prevent_audit_log_mutation(*_args) -> None:
    raise ValueError("Audit logs are immutable and cannot be updated or deleted")


event.listen(AuditLog, "before_update", _prevent_audit_log_mutation)
event.listen(AuditLog, "before_delete", _prevent_audit_log_mutation)
