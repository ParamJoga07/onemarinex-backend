from app.db.session import SessionLocal
from app.db.models.hotels import Hotel
from datetime import datetime

def seed_hotels():
    db = SessionLocal()
    try:
        # Clear existing data to avoid duplicates (optional, but good for testing)
        db.query(Hotel).delete()
        
        hotels_data = [
            # Mumbai Port Area
            {
                "name": "The Oberoi, Mumbai",
                "location": "Nariman Point, Mumbai",
                "distance_from_port": 4.6,
                "rating": 4.8,
                "price_per_night": 25000.0,
                "phone": "+91 22 6632 5757",
                "image_url": "https://images.unsplash.com/photo-1566073771259-6a8506099945",
                "lat": 18.9272,
                "lng": 72.8205
            },
            {
                "name": "Taj Mahal Tower, Mumbai",
                "location": "Apollo Bandar, Colaba, Mumbai",
                "distance_from_port": 1.2,
                "rating": 5.0,
                "price_per_night": 30000.0,
                "phone": "+91 22 6665 3366",
                "image_url": "https://images.unsplash.com/photo-1542314831-068cd1dbfeeb",
                "lat": 18.9218,
                "lng": 72.8333
            },
            {
                "name": "ITC Grand Central",
                "location": "Parel, Mumbai",
                "distance_from_port": 8.5,
                "rating": 5.0,
                "price_per_night": 18000.0,
                "phone": "+91 22 2410 1010",
                "image_url": "https://images.unsplash.com/photo-1571896349842-33c89424de2d",
                "lat": 19.0025,
                "lng": 72.8427
            },
            {
                "name": "Fariyas Hotel Mumbai, Colaba",
                "location": "Colaba, Mumbai",
                "distance_from_port": 0.9,
                "rating": 3.7,
                "price_per_night": 8500.0,
                "phone": "+91 22 6141 6141",
                "image_url": "https://images.unsplash.com/photo-1520250497591-112f2f40a3f4",
                "lat": 18.9168,
                "lng": 72.8277
            },
            {
                "name": "Urban Stays Backpackers Hostel",
                "location": "Fort, Mumbai",
                "distance_from_port": 0.9,
                "rating": 3.9,
                "price_per_night": 1200.0,
                "phone": "+91 98765 43210",
                "image_url": "https://images.unsplash.com/photo-1596272875729-ed2ff7d6d9c5",
                "lat": 18.9568,
                "lng": 72.8427
            },
            # Singapore Port Area
            {
                "name": "Marina Bay Sands",
                "location": "10 Bayfront Ave, Singapore",
                "distance_from_port": 1.9,
                "rating": 4.5,
                "price_per_night": 45000.0, # Approx in INR if user expects consistent currency, but let's assume local units/indicative
                "phone": "+65 6688 8868",
                "image_url": "https://images.unsplash.com/photo-1529653762956-b0a27278509c",
                "lat": 1.2828,
                "lng": 103.8587
            },
            {
                "name": "The Westin Singapore",
                "location": "12 Marina View, Asia Square Tower 2, Singapore",
                "distance_from_port": 1.6,
                "rating": 4.0,
                "price_per_night": 32000.0,
                "phone": "+65 6922 6888",
                "image_url": "https://images.unsplash.com/photo-1541339907198-e08756ebafe3",
                "lat": 1.2778,
                "lng": 103.8525
            },
            {
                "name": "Mandarin Oriental, Singapore",
                "location": "5 Raffles Ave, Singapore",
                "distance_from_port": 2.1,
                "rating": 4.7,
                "price_per_night": 38000.0,
                "phone": "+65 6338 0066",
                "image_url": "https://images.unsplash.com/photo-1582719478250-c89cae4dc85b",
                "lat": 1.2908,
                "lng": 103.8595
            },
            {
                "name": "M Hotel Singapore City Centre",
                "location": "81 Anson Rd, Singapore",
                "distance_from_port": 1.8,
                "rating": 4.0,
                "price_per_night": 18000.0,
                "phone": "+65 6224 1133",
                "image_url": "https://images.unsplash.com/photo-1564501049412-61c2a3083791",
                "lat": 1.2736,
                "lng": 103.8447
            },
            {
                "name": "ST Signature Tanjong Pagar",
                "location": "32 Tras St, Singapore",
                "distance_from_port": 2.0,
                "rating": 4.1,
                "price_per_night": 9000.0,
                "phone": "+65 6291 7050",
                "image_url": "https://images.unsplash.com/photo-1566665797739-1674de7a421a?auto=format&fit=crop&w=800&q=80",
                "lat": 1.2789,
                "lng": 103.8437
            }
        ]
        
        for hotel_info in hotels_data:
            hotel = Hotel(**hotel_info)
            db.add(hotel)
            
        db.commit()
        print(f"✅ Successfully seeded {len(hotels_data)} hotels!")
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error seeding hotels: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    seed_hotels()
