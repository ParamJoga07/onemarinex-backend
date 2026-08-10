from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, func
from sqlalchemy.orm import relationship
from app.db.base import Base

class AgentProfile(Base):
    __tablename__ = "agent_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    
    agency_name = Column(String(255), nullable=False)
    contact_person = Column(String(255), nullable=True)
    location = Column(String(255), nullable=False) # Base location
    assigned_port = Column(String(255), nullable=True) # current assigned port
    gst_number = Column(String(64), nullable=True)
    license_number = Column(String(64), nullable=True)
    status = Column(String(32), server_default="Active") # Active, Inactive
    # Two distinct images, deliberately separate:
    #   profile_image    the contact person's photo, shown on the profile page
    #   agency_logo_url  the agency's logo, printed on the PDF reports
    profile_image = Column(String(512), nullable=True) # URL to image
    agency_logo_url = Column(String(512), nullable=True)
    # The agency's own crew-support number. Kept here rather than on port_rules,
    # which the superadmin owns and every agency at the port shares.
    support_number = Column(String(32), nullable=True)
    agent_identifier = Column(String(64), nullable=True)  # e.g., "12287-28792-87258"
    auth_document_url = Column(String(512), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # --- relationship back to user ---
    user = relationship("User", back_populates="agent_profile")

    def __repr__(self) -> str:
        return f"<AgentProfile id={self.id} user_id={self.user_id} agency={self.agency_name}>"
