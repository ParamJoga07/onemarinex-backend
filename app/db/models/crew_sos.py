from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class CrewSos(Base):
    __tablename__ = "crew_sos_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    crew_profile_id = Column(Integer, ForeignKey("crew_profiles.id", ondelete="CASCADE"), nullable=False)
    cab_booking_id = Column(Integer, ForeignKey("cab_bookings.id", ondelete="SET NULL"), nullable=True, index=True)
    trip_id = Column(String(64), nullable=True, index=True)
    crew_email = Column(String(255), nullable=True)
    sos_email = Column(String(255), nullable=True)
    port_name = Column(String(128), nullable=True)
    vessel = Column(String(128), nullable=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    status = Column(String(32), nullable=False, default="ACTIVE")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User")
    crew_profile = relationship("CrewProfile")
    cab_booking = relationship("CabBooking")
