import requests
import time

time.sleep(2)  # Wait for server to start

try:
    # Test admin page
    response = requests.get('http://127.0.0.1:5000/admin', timeout=10)
    content = response.text
    
    print(f"Admin page status: {response.status_code}")
    
    # Check for ad-related content
    ad_indicators = ['ad-container', 'ad-banner', 'ad-header', 'ad-footer', 'advertisement']
    found_ads = []
    
    for indicator in ad_indicators:
        if indicator in content:
            found_ads.append(indicator)
    
    if found_ads:
        print(f"WARNING: Ads found on admin page: {found_ads}")
    else:
        print("SUCCESS: No ads found on admin page!")
    
    # Test home page for comparison
    response2 = requests.get('http://127.0.0.1:5000/', timeout=10)
    content2 = response2.text
    
    home_ads = []
    for indicator in ad_indicators:
        if indicator in content2:
            home_ads.append(indicator)
    
    if home_ads:
        print(f"Home page has ads (expected): {home_ads}")
    else:
        print("Note: No ads found on home page either")
        
except Exception as e:
    print(f"Error: {e}")
