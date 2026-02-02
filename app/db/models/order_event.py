from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, func, Text
)
from sqlalchemy.orm import relationship
from app.db.base import Base

class OrderEvent(Base):
    __tablename__ = "order_events"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)

    # who posted the event
    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_role = Column(String(32), nullable=True)  # vendor | shipping_company | agent

    # event details
    status = Column(String(64), nullable=False)  # processing|packed|departed_origin|arrived_hub|in_transit|out_for_delivery|delivered|delayed|cancelled|customs_cleared
    location = Column(String, nullable=True)     # e.g. "Jebel Ali, Dubai"
    hub_name = Column(String, nullable=True)     # e.g. "Hub A / Terminal 3"
    note = Column(Text, nullable=True)

    # delay info (optional)
    delay_reason = Column(String, nullable=True)
    delay_hours = Column(Integer, nullable=True)

    # ETA / timestamps
    eta = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    order = relationship("Order")
