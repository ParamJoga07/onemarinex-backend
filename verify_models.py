from app.db.base import Base
from app.db.models.user import User
from app.db.models.crew_profile import CrewProfile
from app.db.models.client_profile import ClientProfile
from datetime import date

def verify_models():
    print("🔄 Verifying model definitions...")
    
    # Check if tables are registered in Base
    expected_tables = {"users", "vendor_profiles", "crew_profiles", "client_profiles"}
    registered_tables = set(Base.metadata.tables.keys())
    
    missing = expected_tables - registered_tables
    if missing:
        print(f"❌ Missing tables in metadata: {missing}")
        return False
    else:
        print("✅ All expected tables are registered in metadata.")

    print("🔄 Verifying relationships...")
    try:
        # Create a dummy user
        user = User(
            email="test@example.com",
            hashed_password="hashed_password",
            role="crew",
            mobile_number="+1234567890"
        )
        
        # Create a crew profile
        crew = CrewProfile(
            user=user,
            full_name="John Doe",
            rank="captain",
            nationality="US",
            passport_number="P1234567",
            date_of_birth=date(1980, 1, 1),
            current_port="Singapore",
            vessel="Explorer 1"
        )
        
        # Verify relationship (back-populates)
        if user.crew_profile != crew:
            print("❌ Crew relationship back-population failed.")
            return False
            
        # Create a client profile
        client = ClientProfile(
            user=user,
            company_name="Shipping Co",
            contact_person="Jane Smith",
            phone_number="+0987654321"
        )
        
        # Verify relationship
        if user.client_profile != client:
            print("❌ Client relationship back-population failed.")
            return False

        print("✅ Model relationships verified successfully!")
        return True

    except Exception as e:
        print(f"❌ Error during relationship verification: {e}")
        return False

if __name__ == "__main__":
    if verify_models():
        print("\n🎉 Model verification passed!")
    else:
        print("\n⚠️  Model verification failed.")
        exit(1)
