from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class ReportSnapshot(Base):
    """An immutable payload used to generate a downloaded operational report.

    Source records remain editable while an incident is handled. A snapshot is
    a separate audit artifact: later crew reassignment, profile edits, vessel
    archival, or timeline updates cannot rewrite what was generated.
    """

    __tablename__ = "report_snapshots"
    __table_args__ = (
        Index("ix_report_snapshots_source", "report_kind", "source_id"),
        Index("ix_report_snapshots_agency_created", "agency_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    report_kind = Column(String(32), nullable=False)
    source_id = Column(Integer, nullable=True)
    source_reference = Column(String(255), nullable=False)
    agency_id = Column(
        Integer,
        ForeignKey("agent_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    vessel_call_id = Column(
        Integer,
        ForeignKey("vessel_calls.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    generated_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    payload = Column(JSON, nullable=False)
    payload_sha256 = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    agency = relationship("AgentProfile")
    vessel_call = relationship("VesselCall")
    generated_by = relationship("User")
