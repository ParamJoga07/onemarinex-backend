from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func, Float
from sqlalchemy.orm import relationship
from app.db.base import Base


class ChatModerationEvent(Base):
    """Complete moderation event log with all signals.

    Fields:
    - Inputs: raw_message, normalized_message
    - Level 1: matched_term, rejected_by, reason_code
    - Level 2: ai_route, ai_model, ai_latency_ms
    - Level 3: decision, category, confidence, reason, moderation_layer
    """
    __tablename__ = "chat_moderation_events"

    id = Column(Integer, primary_key=True, index=True)
    port_id = Column(Integer, ForeignKey("ports.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    chat_message_id = Column(Integer, ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True)

    # Inputs
    raw_message = Column(Text, nullable=False)
    normalized_message = Column(Text, nullable=False)

    # Level 1 signals
    matched_term = Column(String(128), nullable=True)
    rejected_by = Column(String(32), nullable=True)
    reason_code = Column(String(48), nullable=True)

    # Level 2 signals (AI)
    ai_route = Column(String(24), nullable=True)
    ai_model = Column(String(64), nullable=True)
    ai_latency_ms = Column(Integer, nullable=True)
    ai_context_verdict = Column(String(16), nullable=True)

    # Level 3 signals (Policy decision)
    decision = Column(String(16), nullable=False)
    category = Column(String(32), nullable=True)
    confidence = Column(Float, default=0.0)
    reason = Column(Text, nullable=False)
    moderation_layer = Column(String(16), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    port = relationship("Port")
    user = relationship("User")

    def __repr__(self) -> str:
        return (f"<ChatModerationEvent id={self.id} decision={self.decision} "
                f"category={self.category} layer={self.moderation_layer}>")
