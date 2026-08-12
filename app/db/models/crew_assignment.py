from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class CrewAssignment(Base):
    """A crew member's membership of a specific historical vessel call."""

    __tablename__ = "crew_assignments"
    __table_args__ = (
        Index(
            "uq_crew_assignments_active_manifest",
            "vessel_call_id",
            "vessel_crew_id",
            unique=True,
            postgresql_where=text(
                "ended_at IS NULL AND vessel_crew_id IS NOT NULL"
            ),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    vessel_call_id = Column(
        Integer,
        ForeignKey("vessel_calls.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    crew_profile_id = Column(
        Integer,
        ForeignKey("crew_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    vessel_crew_id = Column(
        Integer,
        ForeignKey("vessel_crew.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    crew_name = Column(String(255), nullable=False)
    rank = Column(String(100), nullable=True)
    nationality = Column(String(100), nullable=True)
    hpid = Column(String(100), nullable=True, index=True)
    passport_number = Column(String(64), nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    vessel_call = relationship("VesselCall", back_populates="crew_assignments")
    crew_profile = relationship("CrewProfile")
    vessel_crew = relationship("VesselCrew")
