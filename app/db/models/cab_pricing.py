from sqlalchemy import Column, Integer, String, Float
from app.db.base import Base

class CabPricing(Base):
    __tablename__ = "cab_pricing"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_type = Column(String(64), unique=True, index=True, nullable=False) # Cab AC, Cab Premium AC, Cab XL AC
    base_fare = Column(Float, nullable=False)
    per_km_rate = Column(Float, nullable=False)
    minimum_fare = Column(Float, nullable=False)
