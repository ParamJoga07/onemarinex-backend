from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Numeric, func
from sqlalchemy.orm import relationship

from app.db.base import Base


class ExpenseBill(Base):
    """A shore-leave bill/receipt uploaded by a crew member."""

    __tablename__ = "expense_bills"

    id = Column(Integer, primary_key=True, index=True)
    crew_id = Column(Integer, ForeignKey("crew_profiles.id", ondelete="CASCADE"), nullable=False, index=True)

    merchant = Column(String(255), nullable=False)          # venue / shop name
    amount = Column(Numeric(10, 2), nullable=True)          # total paid (kept for back-compat)
    amount_pre_tax = Column(Numeric(10, 2), nullable=True)  # before taxes — shown to super admin
    amount_post_tax = Column(Numeric(10, 2), nullable=True) # after taxes (paid) — shown to crew
    bill_number = Column(String(128), nullable=True)        # extracted bill / invoice no.
    notes = Column(String(1000), nullable=True)
    bill_date = Column(DateTime(timezone=True), nullable=True)  # when the bill was paid

    # Optional trip link — a bill may belong to a shore pass OR a cab booking.
    shore_pass_id = Column(Integer, ForeignKey("shore_passes.id", ondelete="SET NULL"), nullable=True, index=True)
    cab_booking_id = Column(Integer, ForeignKey("cab_bookings.id", ondelete="SET NULL"), nullable=True, index=True)

    receipt_url = Column(String(512), nullable=False)       # /uploads/expense_bills/…
    receipt_filename = Column(String(255), nullable=False)  # original filename

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    crew = relationship("CrewProfile")
