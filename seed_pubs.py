import os
import sys

# Add the project root to the python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.db.session import SessionLocal
from app.db.models.pub import Pub

def seed_pubs():
    db = SessionLocal()
    try:
        # Clear existing data to ensure we have the latest updates
        db.query(Pub).delete()
        print("Cleared existing pubs data.")

        pubs_data = [
            {
                "name": "10 Downing Street",
                "location_name": "Gachibowli, Hyderabad",
                "distance_from_port": 12.5,
                "rating": 4.2,
                "price_per_person": 1500.0,
                "timings": "12:00 PM - 12:00 AM",
                "service_type": "Dine-in, Bar",
                "popular_for": ["British Decor", "Lunch Buffet", "Shepherd's Pie"],
                "phone": "+91 40 2980 0266",
                "lat": 17.4527,
                "lng": 78.36327,
                "image_url": "https://images.unsplash.com/photo-1514933651103-005eec06c04b?q=80&w=800&auto=format&fit=crop",
                "description": "A classic British-style pub known for its elegant decor and great food."
            },
            {
                "name": "Prost Brew Pub",
                "location_name": "Jubilee Hills, Hyderabad",
                "distance_from_port": 10.2,
                "rating": 4.5,
                "price_per_person": 2000.0,
                "timings": "12:00 PM - 11:30 PM",
                "service_type": "Brewery, Bar",
                "popular_for": ["Craft Beer", "Rooftop Seating", "Pizza"],
                "phone": "+91 40 2355 6235",
                "lat": 17.43482,
                "lng": 78.39867,
                "image_url": "https://images.unsplash.com/photo-1538481199705-c710c4e965fc?q=80&w=800&auto=format&fit=crop",
                "description": "One of the best microbreweries in town with a rustic industrial vibe."
            },
            {
                "name": "Heart Cup Coffee",
                "location_name": "Gachibowli, Hyderabad",
                "distance_from_port": 13.1,
                "rating": 4.3,
                "price_per_person": 1200.0,
                "timings": "10:30 AM - 12:00 AM",
                "service_type": "Cafe, Bar",
                "popular_for": ["Live Music", "Outdoor Seating", "Coffee"],
                "phone": "+91 91000 01133",
                "lat": 17.4597140,
                "lng": 78.3686459,
                "image_url": "https://images.unsplash.com/photo-1543007630-9710e4a00a20?q=80&w=800&auto=format&fit=crop",
                "description": "A popular spot for live music, great coffee, and a relaxed atmosphere."
            },
            {
                "name": "Over The Moon",
                "location_name": "Jubilee Hills, Hyderabad",
                "distance_from_port": 9.8,
                "rating": 4.4,
                "price_per_person": 2500.0,
                "timings": "12:00 PM - 12:00 AM",
                "service_type": "Lounge, Bar",
                "popular_for": ["Skyline View", "Cocktails", "Finger Food"],
                "phone": "+91 40 6604 7111",
                "lat": 17.43384,
                "lng": 78.40693,
                "image_url": "https://images.unsplash.com/photo-1470337458703-46ad1756a187?q=80&w=800&auto=format&fit=crop",
                "description": "A luxurious lounge offering stunning views of the city skyline."
            },
            {
                "name": "Prism Club & Kitchen",
                "location_name": "Financial District, Hyderabad",
                "distance_from_port": 15.4,
                "rating": 4.6,
                "price_per_person": 3000.0,
                "timings": "5:00 PM - 12:00 AM",
                "service_type": "Nightclub, Bar",
                "popular_for": ["Lighting", "Dance Floor", "DJ"],
                "phone": "+91 73374 77999",
                "lat": 17.41727,
                "lng": 78.36952,
                "image_url": "https://images.unsplash.com/photo-1574096079513-d8259312b785?q=80&w=800&auto=format&fit=crop",
                "description": "A high-energy nightclub with state-of-the-art lighting and sound."
            }
        ]

        for pub in pubs_data:
            db_pub = Pub(**pub)
            db.add(db_pub)
        
        db.commit()
        print(f"Successfully seeded {len(pubs_data)} pubs with image URLs.")

    except Exception as e:
        print(f"Error seeding pubs: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_pubs()
