from sqlalchemy import (
    Column, Integer, String, DateTime, JSON, ForeignKey, Numeric, Float, func, UniqueConstraint
)
from sqlalchemy.orm import relationship
from app.db.base import Base

class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        # one order per RFQ
        UniqueConstraint("rfq_id", name="uq_order_rfq"),
    )

    id = Column(Integer, primary_key=True, index=True)
    order_number = Column(String(64), unique=True, index=True, nullable=False)

    rfq_id = Column(Integer, ForeignKey("rfqs.id", ondelete="CASCADE"), nullable=False)
    quote_id = Column(Integer, ForeignKey("rfq_quotes.id", ondelete="SET NULL"), nullable=True)

    buyer_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    vendor_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    vendor_company = Column(String, nullable=True)
    port = Column(String, nullable=True)

    currency = Column(String(8), nullable=False, default="USD")
    items = Column(JSON, nullable=False, default=list)

    shipping_cost = Column(Numeric(12, 2), nullable=False, default=0)
    discount_pct = Column(Float, nullable=False, default=0)
    tax_pct = Column(Float, nullable=False, default=0)
    subtotal = Column(Numeric(12, 2), nullable=False, default=0)
    tax_amount = Column(Numeric(12, 2), nullable=False, default=0)
    grand_total = Column(Numeric(12, 2), nullable=False, default=0)

    delivery_time_days = Column(Integer, nullable=True)
    notes = Column(String, nullable=True)

    status = Column(String(32), nullable=False, server_default="confirmed")  # confirmed|processing|fulfilled|cancelled
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    rfq = relationship("RFQ")
    quote = relationship("RFQQuote")
