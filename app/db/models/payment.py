from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Numeric, func
from sqlalchemy.orm import relationship

from app.db.base import Base


class Payment(Base):
    """A crew payment (cab fare, bill settlement) via Razorpay."""

    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    crew_id = Column(Integer, ForeignKey("crew_profiles.id", ondelete="SET NULL"), nullable=True, index=True)

    purpose = Column(String(64), nullable=False, default="bill")   # bill | cab | package
    reference = Column(String(255), nullable=True)                 # merchant / booking id / free text
    amount = Column(Numeric(10, 2), nullable=False)                # rupees
    currency = Column(String(8), nullable=False, default="INR")

    razorpay_order_id = Column(String(64), nullable=True, index=True)
    razorpay_payment_id = Column(String(64), nullable=True)
    # created -> paid | failed. Mock-mode payments still transition to paid.
    status = Column(String(24), nullable=False, default="created")
    is_mock = Column(Integer, nullable=False, default=0)           # 1 when created without live Razorpay creds

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    paid_at = Column(DateTime(timezone=True), nullable=True)

    crew = relationship("CrewProfile")
