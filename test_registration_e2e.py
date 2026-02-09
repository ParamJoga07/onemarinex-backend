import requests
import sys

def test_crew_registration():
    url = "http://localhost:8000/api/v1/registration/crew"
    payload = {
        "email": "crew_test_new@example.com",
        "password": "password123",
        "mobile_number": "+1234567890",
        "full_name": "Test Crew",
        "rank": "captain",
        "nationality": "US",
        "passport_number": "P9876543",
        "date_of_birth": "1990-01-01"
    }

    print(f"🚀 Testing Crew Registration API at {url}...")
    try:
        response = requests.post(url, json=payload)
        
        if response.status_code == 201:
            print("✅ Registration Successful!")
            data = response.json()
            print(f"Access Token: {data['access_token'][:20]}...")
            print(f"Role: {data['role']}")
            return True
        elif response.status_code == 409:
            print("⚠️ User already exists (Conflict). This is expected if run multiple times.")
            return True
        else:
            print(f"❌ Registration Failed! Status: {response.status_code}")
            print(f"Error detail: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Error during API call: {e}")
        return False

if __name__ == "__main__":
    if test_crew_registration():
        print("\n🎉 End-to-End Registration Test Passed!")
    else:
        print("\n⚠️  End-to-End Registration Test Failed.")
        sys.exit(1)
