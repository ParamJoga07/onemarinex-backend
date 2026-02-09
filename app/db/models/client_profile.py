from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, func
from sqlalchemy.orm import relationship
from app.db.base import Base

class ClientProfile(Base):
    __tablename__ = "client_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)

    company_name = Column(String(255), nullable=False)
    contact_person = Column(String(120), nullable=True)
    phone_number = Column(String(32), nullable=True)
    
    verification_status = Column(String(32), default="pending")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # --- relationship back to user ---
    user = relationship("User", back_populates="client_profile")

    def __repr__(self) -> str:
        return f"<ClientProfile id={self.id} user_id={self.user_id} company={self.company_name}>"
