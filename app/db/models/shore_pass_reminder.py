from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func

from app.db.base import Base


class ShorePassReminder(Base):
    """Dedup record so the reminder scheduler never sends the same
    return/critical-return WhatsApp reminder twice for the same shore pass,
    even if multiple app instances race on the same poll tick."""
    __tablename__ = "shore_pass_reminders"

    id = Column(Integer, primary_key=True, index=True)
    shore_pass_id = Column(Integer, ForeignKey("shore_passes.id", ondelete="CASCADE"), nullable=False, index=True)
    reminder_type = Column(String(32), nullable=False)  # "return_2h" | "critical_30m"
    sent_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("shore_pass_id", "reminder_type", name="uq_shore_pass_reminder"),
    )
