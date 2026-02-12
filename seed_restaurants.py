from app.db.session import SessionLocal
from app.db.models.restaurant import Restaurant
from datetime import datetime

def seed_restaurants():
    db = SessionLocal()
    try:
        # Clear existing data to avoid duplicates
        db.query(Restaurant).delete()
        
        restaurants_data = [
            {
                "name": "Paradise Biryani",
                "location_name": "Secunderabad, Hyderabad",
                "distance_from_port": 2.5,
                "rating": 4.5,
                "price_per_person": 500.0,
                "timings": "11:00 AM - 11:00 PM",
                "service_type": "Biryani, Kebabs",
                "popular_for": ["World Famous Biryani", "Double ka Meetha"],
                "phone": "+91 40 6666 1111",
                "lat": 17.4399,
                "lng": 78.4983,
                "image_url": "https://images.unsplash.com/photo-1589302168068-964664d93dc0?auto=format&fit=crop&w=800&q=80",
                "menu_images": [
                    "https://images.unsplash.com/photo-1559339352-11d035aa65de?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1626082927389-6cd097cdc6ec?auto=format&fit=crop&w=800&q=80"
                ],
                "description": "Legendary biryani house serving authentic Hyderabadi cuisine since 1953.",
                "address": "SD Road, Secunderabad, Telangana 500003"
            },
            {
                "name": "Bawarchi",
                "location_name": "RTC X Roads, Hyderabad",
                "distance_from_port": 4.2,
                "rating": 4.3,
                "price_per_person": 400.0,
                "timings": "12:00 PM - 12:00 AM",
                "service_type": "Mughlai, North Indian",
                "popular_for": ["Mutton Biryani", "Chicken Tikka"],
                "phone": "+91 40 2760 0333",
                "lat": 17.4042,
                "lng": 78.4913,
                "image_url": "https://images.unsplash.com/photo-1633945274405-b6c8069047b0?auto=format&fit=crop&w=800&q=80",
                "menu_images": [
                    "https://images.unsplash.com/photo-1594179047519-f347310d3322?auto=format&fit=crop&w=800&q=80"
                ],
                "description": "The original Bawarchi, famous for its melt-in-the-mouth biryani and kebabs.",
                "address": "Musheerabad Road, RTC X Roads, Hyderabad 500020"
            },
            {
                "name": "Shah Ghouse Hotel & Restaurant",
                "location_name": "Gachibowli, Hyderabad",
                "distance_from_port": 12.0,
                "rating": 4.2,
                "price_per_person": 450.0,
                "timings": "11:00 AM - 1:00 AM",
                "service_type": "Hyderabadi, Mughlai",
                "popular_for": ["Special Biryani", "Haleem (Seasonal)"],
                "phone": "+91 97003 45678",
                "lat": 17.4421,
                "lng": 78.3564,
                "image_url": "https://images.unsplash.com/photo-1603894584373-5ac82b2ae398?auto=format&fit=crop&w=800&q=80",
                "menu_images": [
                    "https://images.unsplash.com/photo-1514933651103-005eec06c04b?auto=format&fit=crop&w=800&q=80"
                ],
                "description": "Known for its rich flavours and quick service in the IT hub.",
                "address": "Indira Nagar, Gachibowli, Hyderabad 500032"
            },
            {
                "name": "Minerva Coffee Shop",
                "location_name": "Himayatnagar, Hyderabad",
                "distance_from_port": 5.5,
                "rating": 4.4,
                "price_per_person": 300.0,
                "timings": "7:00 AM - 10:30 PM",
                "service_type": "South Indian, Pure Veg",
                "popular_for": ["Button Idli", "Filter Coffee"],
                "phone": "+91 40 2322 0420",
                "lat": 17.3999,
                "lng": 78.4839,
                "image_url": "https://images.unsplash.com/photo-1589302168068-964664d93dc0?auto=format&fit=crop&w=800&q=80",
                "menu_images": [
                    "https://images.unsplash.com/photo-1610192244261-3f33de3f55e4?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1626074353765-517a681e40be?auto=format&fit=crop&w=800&q=80"
                ],
                "description": "A classic spot for authentic South Indian breakfast and snacks.",
                "address": "Himayatnagar Main Rd, Hyderabad 500029"
            },
            {
                "name": "Pakka Local",
                "location_name": "Kondapur, Hyderabad",
                "distance_from_port": 15.0,
                "rating": 4.3,
                "price_per_person": 600.0,
                "timings": "12:00 PM - 11:30 PM",
                "service_type": "Andhra, Rayalaseema",
                "popular_for": ["Bhimavaram Prawn Biryani", "Chitti Muthyala Pulav"],
                "phone": "+91 40 4851 5151",
                "lat": 17.4623,
                "lng": 78.3639,
                "image_url": "https://images.unsplash.com/photo-1589302168068-964664d93dc0?auto=format&fit=crop&w=800&q=80",
                "menu_images": [
                    "https://images.unsplash.com/photo-1543353071-873f17a7a088?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1514327605112-b887c0e61c0a?auto=format&fit=crop&w=800&q=80"
                ],
                "description": "Authentic Telugu cuisine with a rustic village-style ambiance.",
                "address": "Main Road, Kondapur, Hyderabad 500084"
            }
        ]
        
        for res_info in restaurants_data:
            res = Restaurant(**res_info)
            db.add(res)
            
        db.commit()
        print(f"✅ Successfully seeded {len(restaurants_data)} restaurants!")
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error seeding restaurants: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    seed_restaurants()
