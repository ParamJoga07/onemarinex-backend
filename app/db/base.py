# app/db/base.py
from sqlalchemy.orm import declarative_base

# Shared declarative base
Base = declarative_base()

# Import models so they're registered with Base.metadata
# (No engine/session imports here to avoid circulars)
from app.db.models import user            # noqa: F401
from app.db.models import vendor_profile  # noqa: F401
from app.db.models import file_asset      # noqa: F401
from app.db.models import password_reset  # noqa: F401
from app.db.models.order import Order
from app.db.models.order_event import OrderEvent 
