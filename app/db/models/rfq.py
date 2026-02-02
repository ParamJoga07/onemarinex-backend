from sqlalchemy import Column, Integer, String, DateTime, JSON, func, ForeignKey
from sqlalchemy.orm import relationship
from app.db.base import Base

class RFQ(Base):
    __tablename__ = "rfqs"

    id = Column(Integer, primary_key=True, index=True)

    # Core
    title = Column(String(255), nullable=False)
    buyer_company = Column(String(255), nullable=False)
    port = Column(String(120), nullable=False)

    # Deadlines & budget
    deadline_days = Column(Integer, nullable=False, default=5)
    budget_min = Column(Integer, nullable=True)
    budget_max = Column(Integer, nullable=True)

    # JSON payloads
    required_items = Column(JSON, default=list, nullable=False)
    tags = Column(JSON, default=list, nullable=False)
    terms = Column(JSON, default=dict, nullable=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # --- owner ---
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user = relationship("User", back_populates="rfqs")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RFQ id={self.id} title={self.title!r} port={self.port!r} user_id={self.user_id}>"
