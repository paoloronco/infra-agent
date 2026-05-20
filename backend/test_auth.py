#!/usr/bin/env python3
"""Test authentication system."""

import requests
import json

def test_auth_system():
    """Test the complete authentication system."""
    
    base_url = "http://localhost:8000"
    
    print("🔐 Testing Authentication System")
    print("=" * 50)
    
    # Test 1: Check initial status (should be disabled)
    print("\n1. Testing initial auth status...")
    try:
        response = requests.get(f"{base_url}/api/auth/config")
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   Auth enabled: {data.get('enabled', False)}")
        else:
            print(f"   Error: {response.text}")
    except Exception as e:
        print(f"   Exception: {e}")
    
    # Test 2: Enable authentication
    print("\n2. Enabling authentication...")
    try:
        response = requests.put(
            f"{base_url}/api/auth/config",
            json={"enabled": True},
            auth=("admin", "admin123")
        )
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   Message: {data.get('message', '')}")
        else:
            print(f"   Error: {response.text}")
    except Exception as e:
        print(f"   Exception: {e}")
    
    # Test 3: Check status after enabling
    print("\n3. Checking auth status after enabling...")
    try:
        response = requests.get(f"{base_url}/api/auth/config", auth=("admin", "admin123"))
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   Auth enabled: {data.get('enabled', False)}")
            print(f"   Current user: {data.get('current_user', 'N/A')}")
        else:
            print(f"   Error: {response.text}")
    except Exception as e:
        print(f"   Exception: {e}")
    
    # Test 4: Test invalid credentials
    print("\n4. Testing invalid credentials...")
    try:
        response = requests.get(f"{base_url}/api/auth/config", auth=("admin", "wrong"))
        print(f"   Status: {response.status_code}")
        if response.status_code == 401:
            print("   ✅ Invalid credentials correctly rejected")
        else:
            print(f"   ❌ Should have rejected invalid credentials")
    except Exception as e:
        print(f"   Exception: {e}")
    
    # Test 5: Create a new user
    print("\n5. Creating a new user...")
    try:
        response = requests.post(
            f"{base_url}/api/auth/users",
            json={"username": "testuser", "password": "testpass123", "is_admin": False},
            auth=("admin", "admin123")
        )
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   Message: {data.get('message', '')}")
        else:
            print(f"   Error: {response.text}")
    except Exception as e:
        print(f"   Exception: {e}")
    
    # Test 6: List users
    print("\n6. Listing users...")
    try:
        response = requests.get(f"{base_url}/api/auth/users", auth=("admin", "admin123"))
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            users = response.json()
            print(f"   Users found: {len(users)}")
            for user in users:
                print(f"   - {user['username']} (admin: {user['is_admin']}, active: {user['is_active']})")
        else:
            print(f"   Error: {response.text}")
    except Exception as e:
        print(f"   Exception: {e}")
    
    # Test 7: Reset password
    print("\n7. Resetting user password...")
    try:
        response = requests.post(
            f"{base_url}/api/auth/reset-password/testuser",
            auth=("admin", "admin123")
        )
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   New password: {data.get('new_password', '')}")
        else:
            print(f"   Error: {response.text}")
    except Exception as e:
        print(f"   Exception: {e}")
    
    # Test 8: Delete user
    print("\n8. Deleting test user...")
    try:
        response = requests.delete(
            f"{base_url}/api/auth/users/testuser",
            auth=("admin", "admin123")
        )
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   Message: {data.get('message', '')}")
        else:
            print(f"   Error: {response.text}")
    except Exception as e:
        print(f"   Exception: {e}")
    
    # Test 9: Disable authentication
    print("\n9. Disabling authentication...")
    try:
        response = requests.put(
            f"{base_url}/api/auth/config",
            json={"enabled": False},
            auth=("admin", "admin123")
        )
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   Message: {data.get('message', '')}")
        else:
            print(f"   Error: {response.text}")
    except Exception as e:
        print(f"   Exception: {e}")
    
    # Test 10: Final status check
    print("\n10. Final auth status check...")
    try:
        response = requests.get(f"{base_url}/api/auth/config")
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   Auth enabled: {data.get('enabled', False)}")
        else:
            print(f"   Error: {response.text}")
    except Exception as e:
        print(f"   Exception: {e}")
    
    print("\n🎉 Authentication system test completed!")

if __name__ == "__main__":
    test_auth_system()
