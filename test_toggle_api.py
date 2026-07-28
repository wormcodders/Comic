"""Test the toggle_library API endpoint"""
import requests
import json

# Test 1: Test without authentication (should fail with 401)
print("Test 1: Without authentication...")
headers = {'Content-Type': 'application/json'}
data = {'comic_id': 1}
response = requests.post('http://127.0.0.1:5000/api/toggle_library', 
                        headers=headers, json=data)
print(f"  Status: {response.status_code}")
print(f"  Response: {response.text}")
print()

# Test 2: Test with invalid JSON (should fail with 400)
print("Test 2: With invalid JSON...")
response = requests.post('http://127.0.0.1:5000/api/toggle_library',
                        headers={'Content-Type': 'application/json'},
                        data='invalid json')
print(f"  Status: {response.status_code}")
print(f"  Response: {response.text}")
print()

# Test 3: Test with missing comic_id (should fail with 400)
print("Test 3: With missing comic_id...")
response = requests.post('http://127.0.0.1:5000/api/toggle_library',
                        headers=headers, json={})
print(f"  Status: {response.status_code}")
print(f"  Response: {response.text}")
print()

print("API endpoint tests completed!")
print("Note: Authenticated tests require a logged-in session.")
