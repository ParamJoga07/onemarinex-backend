from sqlalchemy import Column, Integer, String, Date, ForeignKey, DateTime, func, Boolean
from sqlalchemy.orm import relationship
from app.db.base import Base

class CrewProfile(Base):
    __tablename__ = "crew_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)

    full_name = Column(String(255), nullable=False)
    rank = Column(String(64), nullable=False)
    nationality = Column(String(2), nullable=False)  # ISO Alpha-2
    passport_number = Column(String(64), nullable=True)
    hpid = Column(String(64), nullable=True, unique=True)
    date_of_birth = Column(Date, nullable=True)
    
    # Professional details
    current_port = Column(String(128), nullable=True)
    vessel = Column(String(128), nullable=True)
    # The vessel this crew member picked, which is not the same thing as one
    # they are assigned to. It decides whether a crew member with no assignment
    # is waiting on an agent-managed ship or aboard one no agency runs here —
    # two situations the shore leave card has to tell apart. Stored by id
    # because the list now spans every port and two ships can share a name.
    selected_vessel_id = Column(
        Integer, ForeignKey("vessels.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    ride_otp = Column(String(4), nullable=True) # Lifetime OTP for ride starts
    sos_email = Column(String(255), nullable=True) # SOS Configration ship's email
    
    # Privacy & Notification settings
    data_sharing = Column(Boolean, default=True)
    share_visits = Column(Boolean, default=True)
    safety_tracking = Column(Boolean, default=True)
    communication = Column(Boolean, default=True)
    notifications = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # --- relationship back to user ---
    user = relationship("User", back_populates="crew_profile")
    # A deleted/recreated account must not erase historical trips. The booking
    # keeps its immutable vessel-call snapshots and the nullable FK is cleared.
    cab_bookings = relationship("CabBooking", back_populates="crew")

    def __repr__(self) -> str:
        return f"<CrewProfile id={self.id} user_id={self.user_id} rank={self.rank}>"
