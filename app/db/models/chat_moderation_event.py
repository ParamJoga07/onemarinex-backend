from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.db.base import Base


class ChatModerationEvent(Base):
    __tablename__ = "chat_moderation_events"

    id = Column(Integer, primary_key=True, index=True)
    port_id = Column(Integer, ForeignKey("ports.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    chat_message_id = Column(Integer, ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True)
    raw_message = Column(Text, nullable=False)
    normalized_message = Column(Text, nullable=False)
    decision = Column(String(16), nullable=False)
    rejected_by = Column(String(32), nullable=True)
    reason_code = Column(String(48), nullable=True)
    matched_term = Column(String(128), nullable=True)
    ai_route = Column(String(24), nullable=True)
    ai_model = Column(String(64), nullable=True)
    ai_latency_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    port = relationship("Port")
    user = relationship("User")

    def __repr__(self) -> str:
        return f"<ChatModerationEvent id={self.id} decision={self.decision} rejected_by={self.rejected_by}>"
