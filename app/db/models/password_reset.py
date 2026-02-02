from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from datetime import datetime, timedelta
from app.db.base import Base  

class PasswordReset(Base):
    __tablename__ = "password_resets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    token = Column(String, unique=True, index=True, nullable=False)
    expires_at = Column(DateTime, default=lambda: datetime.utcnow() + timedelta(hours=1))
