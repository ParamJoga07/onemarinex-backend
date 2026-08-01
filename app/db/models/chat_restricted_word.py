from sqlalchemy import Column, Integer, String, Boolean, DateTime, func
from app.db.base import Base


class ChatRestrictedWord(Base):
    __tablename__ = "chat_restricted_words"

    id = Column(Integer, primary_key=True, index=True)
    word = Column(String(128), unique=True, index=True, nullable=False)
    category = Column(String(64), nullable=True)
    is_phrase = Column(Boolean, nullable=False)
    is_active = Column(Boolean, default=True)
    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<ChatRestrictedWord id={self.id} word={self.word} category={self.category}>"
