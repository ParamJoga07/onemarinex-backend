from sqlalchemy import Column, Integer, String, Float, DateTime, JSON, ForeignKey, Enum as SQLEnum, Numeric
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

from app.db.base import Base


class BookingStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    DRIVER_ASSIGNED = "driver_assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class VehicleType(str, enum.Enum):
    AC = "ac"
    PREMIUM = "premium"
    XL = "xl"


class CabBooking(Base):
    __tablename__ = "cab_bookings"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(String, unique=True, index=True, nullable=False)  # CAB-XXXXXXXX
    
    # Crew relationship
    crew_id = Column(Integer, ForeignKey("crew_profiles.id"), nullable=False)
    crew = relationship("CrewProfile", back_populates="cab_bookings")
    
    # Pickup details
    pickup_address = Column(String, nullable=False)
    pickup_lat = Column(Float, nullable=False)
    pickup_lng = Column(Float, nullable=False)
    
    # Drop details
    drop_address = Column(String, nullable=False)
    drop_lat = Column(Float, nullable=False)
    drop_lng = Column(Float, nullable=False)
    
    # Vehicle details
    vehicle_type = Column(SQLEnum(VehicleType), nullable=False)
    vehicle_name = Column(String, nullable=False)
    estimated_price = Column(Numeric(10, 2), nullable=False)
    distance_km = Column(Float, nullable=False)
    
    # Passenger details
    num_passengers = Column(Integer, nullable=False, default=1)
    crew_member_ids = Column(JSON, nullable=True)  # List of HeyPorts IDs for group bookings
    
    # Scheduling
    scheduled_time = Column(DateTime, nullable=True)
    
    # OTP and driver details
    otp = Column(String(4), nullable=False)  # 4-digit OTP
    driver_name = Column(String, nullable=True)
    driver_phone = Column(String, nullable=True)
    agent_number = Column(String, default="+91 9876543251")
    
    # Status
    status = Column(SQLEnum(BookingStatus), default=BookingStatus.PENDING, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
