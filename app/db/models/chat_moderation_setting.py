from sqlalchemy import Column, Integer, String, Boolean, DateTime, func
from app.db.base import Base


class ChatModerationSetting(Base):
    __tablename__ = "chat_moderation_settings"

    id = Column(Integer, primary_key=True, index=True)
    max_message_length = Column(Integer, default=200)
    rate_limit_count = Column(Integer, default=5)
    rate_limit_window_seconds = Column(Integer, default=10)
    duplicate_window_seconds = Column(Integer, default=60)
    language_ai_enabled = Column(Boolean, default=True)
    moderation_ai_enabled = Column(Boolean, default=True)
    fail_closed = Column(Boolean, default=True)
    block_external_links = Column(Boolean, default=False)
    block_contact_info = Column(Boolean, default=False)
    block_payment_info = Column(Boolean, default=False)
    updated_by = Column(String(255), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<ChatModerationSetting id={self.id} max_message_length={self.max_message_length}>"
