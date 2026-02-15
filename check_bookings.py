
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.base import Base
from app.db.models.cab_booking import CabBooking
from app.core.config import settings

# Adjust import path if needed based on execution context
import sys
import os
sys.path.append(os.getcwd())

# Assuming settings connects to SQLite or similar
# If settings fails, fallback to direct DB path if known, e.g. "sqlite:///./sql_app.db"

try:
    SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL
except Exception as e:
    print(f"Failed to load settings: {e}")
    # Fallback to default if settings not loaded
    SQLALCHEMY_DATABASE_URL = "sqlite:///./sql_app.db" # Check if this is correct based on project

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in str(SQLALCHEMY_DATABASE_URL) else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def check_bookings():
    db = SessionLocal()
    try:
        bookings = db.query(CabBooking).all()
        print(f"Total cab bookings found: {len(bookings)}")
        for booking in bookings:
            print(f"Booking ID: {booking.booking_id}, Price: {booking.estimated_price}, Type: {type(booking.estimated_price)}")
            
            if booking.estimated_price == 0:
                print(f"WARNING: Price is 0 for booking {booking.booking_id}")
    except Exception as e:
        print(f"Error checking bookings: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    check_bookings()
