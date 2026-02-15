
from fastapi.testclient import TestClient
from app.main import app
from app.api.v1.routes_auth import get_current_user
from app.db.models.user import User
from app.db.models.crew_profile import CrewProfile
from app.db.session import get_db

dummy_user = User(id=1, email="test@example.com", role="crew")

def override_get_current_user():
    return dummy_user

app.dependency_overrides[get_current_user] = override_get_current_user

client = TestClient(app)

def test_create_and_check_booking():
    # 1. Create a dummy booking
    payload = {
        "pickup_address": "Test Pickup",
        "pickup_lat": 17.0,
        "pickup_lng": 83.0,
        "drop_address": "Test Drop",
        "drop_lat": 17.1,
        "drop_lng": 83.1,
        "vehicle_type": "ac",
        "vehicle_name": "Cab AC",
        "estimated_price": 427.50,
        "distance_km": 10.0,
        "num_passengers": 1
    }
    
    print("Sending payload with estimated_price: 427.50")
    response = client.post("/api/v1/crew/cab/book", json=payload)
    
    if response.status_code != 200:
        print(f"Failed to create booking: {response.status_code}")
        print(response.json())
        return

    data = response.json()
    booking_id = data["booking_id"]
    print(f"Booking created: {booking_id}")

    # 2. Verify in DB (using API to read back)
    # The API might read back using get_booking_details or history
    # Let's try get_booking_details
    
    response = client.get(f"/api/v1/crew/cab/bookings/{booking_id}")
    if response.status_code != 200:
         print(f"Failed to fetch booking details: {response.status_code}")
         print(response.json())
         return

    details = response.json()
    print(f"Fetched details: Estimated Price = {details.get('estimated_price')}, Type: {type(details.get('estimated_price'))}")
    
    if details.get('estimated_price') == 427.5:
        print("SUCCESS: Price saved and retrieved correctly.")
    else:
        print("FAILURE: Price mismatch.")

if __name__ == "__main__":
    try:
        test_create_and_check_booking()
    except Exception as e:
        print(f"Error: {e}")
