# app/db/models/rfq_quote.py
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    JSON,
    ForeignKey,
    Numeric,
    Float,
    func,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from app.db.base import Base


class RFQQuote(Base):
    __tablename__ = "rfq_quotes"
    __table_args__ = (
        UniqueConstraint("rfq_id", "vendor_user_id", name="uq_rfq_vendor_quote"),
    )

    id = Column(Integer, primary_key=True, index=True)

    # links
    rfq_id = Column(Integer, ForeignKey("rfqs.id", ondelete="CASCADE"), nullable=False)
    vendor_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # meta
    currency = Column(String(8), nullable=False, default="USD")

    # items: [{name, quantity, unit, unit_price, line_total}]
    items = Column(JSON, nullable=False, default=list)

    # cost breakdown
    shipping_cost = Column(Numeric(12, 2), nullable=False, default=0)
    discount_pct = Column(Float, nullable=False, default=0)
    tax_pct = Column(Float, nullable=False, default=0)

    subtotal = Column(Numeric(12, 2), nullable=False, default=0)
    tax_amount = Column(Numeric(12, 2), nullable=False, default=0)
    grand_total = Column(Numeric(12, 2), nullable=False, default=0)

    delivery_time_days = Column(Integer, nullable=True)
    vendor_notes = Column(String, nullable=True)

    status = Column(String(32), nullable=False, server_default="submitted")  # submitted|accepted|rejected|withdrawn
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # relationships (no back_populates required)
    rfq = relationship("RFQ")
    vendor = relationship("User")
