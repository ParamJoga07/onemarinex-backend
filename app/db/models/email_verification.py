from sqlalchemy import Column, Integer, String, DateTime, Boolean
from datetime import datetime, timedelta
from app.db.base import Base


class EmailVerification(Base):
    """Pre-registration email OTP. Keyed by email (no user exists yet) so the
    account is only created once the code is verified ("block at registration").
    New table → auto-created by create_all; no Alembic migration on `users`.
    """
    __tablename__ = "email_verifications"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, index=True, nullable=False)
    code_hash = Column(String, nullable=False)  # bcrypt hash of the 6-digit code
    expires_at = Column(DateTime, nullable=False, default=lambda: datetime.utcnow() + timedelta(minutes=10))
    attempts = Column(Integer, default=0, nullable=False)  # failed verify attempts
    verified = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
