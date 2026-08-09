from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from app.db.base import Base
from app.db.types import UTCDateTime


class LoginEvent(Base):
    """One row per successful login.

    Nothing recorded logins before this: no `last_login` column, no audit table.
    Registration counts can be reconstructed from `users.created_at`, but login
    history cannot be reconstructed at all, so these counts necessarily start
    from the day this ships. The superadmin screen says so rather than showing a
    small number that looks like a decline.

    Drivers live in their own table rather than `users`, so exactly one of
    `user_id` / `driver_id` is set. `role` and `email` are copied in so the
    counts survive the account being deleted.
    """

    __tablename__ = "login_events"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    driver_id = Column(Integer, ForeignKey("drivers.id", ondelete="SET NULL"), nullable=True, index=True)

    role = Column(String(32), nullable=False, index=True)
    email = Column(String(255), nullable=True)

    created_at = Column(UTCDateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<LoginEvent id={self.id} role={self.role} at={self.created_at}>"
