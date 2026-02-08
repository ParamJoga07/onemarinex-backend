import urllib.request
import urllib.error
import json
import ssl

BASE_URL = "http://127.0.0.1:8000/api/v1"

def make_request(url, method="GET", data=None):
    req = urllib.request.Request(url, method=method)
    if data:
        req.add_header('Content-Type', 'application/json')
        req.data = json.dumps(data).encode('utf-8')
    
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except urllib.error.URLError as e:
        return None, str(e)

def test_endpoints():
    print("Testing endpoints...")
    
    # 1. Login (should return 401/422/200 OK)
    # We send dummy data, likely 401 or 422
    status, body = make_request(f"{BASE_URL}/auth/login", "POST", {"email": "test@example.com", "password": "pass"})
    print(f"POST /auth/login: {status}")

    # 2. Signup
    status, body = make_request(f"{BASE_URL}/auth/signup", "POST", {"email": "test@example.com", "password": "pass", "role": "vendor"})
    print(f"POST /auth/signup: {status}")

    # 3. Old duplicate vendor profile (should be GONE -> 404)
    status, body = make_request(f"{BASE_URL}/auth/vendor/profile", "POST", {})
    print(f"POST /auth/vendor/profile: {status}") 
    if status == 404:
        print("SUCCESS: Duplicate route /auth/vendor/profile is gone.")
    else:
        print(f"FAILURE: Duplicate route /auth/vendor/profile returned {status}")

    # 4. Correct vendor profile (should be 422 or 401/403)
    # sending empty body might trigger 422 (Unprocessable Entity) because of missing form fields
    status, body = make_request(f"{BASE_URL}/vendor/profile", "POST", {}) # sending json to form endpoint might error but verify it exists
    print(f"POST /vendor/profile status: {status}")
    if status in [401, 403, 422, 400]: 
        print("SUCCESS: Correct route /vendor/profile is active.")
    else:
        print(f"FAILURE: Correct route /vendor/profile returned {status}")

if __name__ == "__main__":
    try:
        test_endpoints()
    except Exception as e:
        print(f"Script failed: {e}")
