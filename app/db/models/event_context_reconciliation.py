from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class EventContextReconciliation(Base):
    """Append-only audit record for a manual historical-context decision."""

    __tablename__ = "event_context_reconciliations"
    __table_args__ = (
        Index(
            "ix_event_context_reconciliations_source",
            "record_kind",
            "record_id",
            "created_at",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    record_kind = Column(String(16), nullable=False)
    record_id = Column(Integer, nullable=False)
    previous_context = Column(JSON, nullable=False)
    resolved_context = Column(JSON, nullable=False)
    evidence_type = Column(String(32), nullable=False)
    evidence_reference = Column(String(255), nullable=True)
    notes = Column(Text, nullable=False)
    reconciled_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    reconciled_by = relationship("User")
