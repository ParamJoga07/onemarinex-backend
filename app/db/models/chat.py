from sqlalchemy import Column, Integer, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    port_id = Column(Integer, ForeignKey("ports.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    reply_to_id = Column(
        Integer,
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    message = Column(Text, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    edited_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    port = relationship("Port")
    user = relationship("User")
    reply_to = relationship("ChatMessage", remote_side=[id], foreign_keys=[reply_to_id])

    def __repr__(self) -> str:
        return f"<ChatMessage id={self.id} port_id={self.port_id} user_id={self.user_id}>"
