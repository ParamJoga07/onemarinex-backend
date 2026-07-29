from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Numeric, func
from sqlalchemy.orm import relationship

from app.db.base import Base


class ExpenseBill(Base):
    """A shore-leave bill/receipt uploaded by a crew member."""

    __tablename__ = "expense_bills"

    id = Column(Integer, primary_key=True, index=True)
    crew_id = Column(Integer, ForeignKey("crew_profiles.id", ondelete="CASCADE"), nullable=False, index=True)

    merchant = Column(String(255), nullable=False)          # venue / shop name
    amount = Column(Numeric(10, 2), nullable=True)          # optional — bill total
    notes = Column(String(1000), nullable=True)
    bill_date = Column(DateTime(timezone=True), nullable=True)  # when the bill was paid

    receipt_url = Column(String(512), nullable=False)       # /uploads/expense_bills/…
    receipt_filename = Column(String(255), nullable=False)  # original filename

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    crew = relationship("CrewProfile")
