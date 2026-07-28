#!/usr/bin/env python
"""Debug home route"""

from app import app, db
from models import Ad

def test_home_route():
    """Test the home route directly"""
    with app.test_client() as client:
        try:
            response = client.get('/')
            print(f"Status Code: {response.status_code}")
            if response.status_code == 500:
                print("Error occurred, checking app context...")
                
            # Check ads in database
            with app.app_context():
                ads = Ad.query.filter_by(is_active=True).all()
                print(f"Active ads in database: {len(ads)}")
                for ad in ads:
                    print(f"  - {ad.title} ({ad.placement})")
                    
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()

if __name__ == '__main__':
    test_home_route()