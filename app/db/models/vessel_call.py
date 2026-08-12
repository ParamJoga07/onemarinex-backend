from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class VesselCall(Base):
    """One agency operating one vessel during one port call.

    ``vessels`` is the canonical ship. This row is the historical operational
    boundary that must not change when the ship is reassigned or archived.
    Snapshot fields keep reports intelligible even if a referenced profile,
    port, or vessel is later retired.
    """

    __tablename__ = "vessel_calls"
    __table_args__ = (
        Index(
            "uq_vessel_calls_active_vessel",
            "vessel_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL AND vessel_id IS NOT NULL"),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    vessel_id = Column(
        Integer, ForeignKey("vessels.id", ondelete="SET NULL"), nullable=True, index=True
    )
    agency_id = Column(
        Integer,
        ForeignKey("agent_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    port_id = Column(
        Integer, ForeignKey("ports.id", ondelete="SET NULL"), nullable=True, index=True
    )

    vessel_name = Column(String(255), nullable=False)
    imo_number = Column(String(100), nullable=True)
    flag = Column(String(100), nullable=True)
    agency_name = Column(String(255), nullable=True)
    port_name = Column(String(255), nullable=True)

    eta = Column(DateTime(timezone=True), nullable=True)
    etd = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(32), nullable=False, default="ACTIVE", server_default="ACTIVE")

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    vessel = relationship("Vessel", back_populates="calls")
    agency = relationship("AgentProfile")
    port = relationship("Port")
    crew_assignments = relationship(
        "CrewAssignment", back_populates="vessel_call", order_by="CrewAssignment.id"
    )
