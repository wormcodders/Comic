#!/usr/bin/env python
"""Debug script to test app initialization"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from models import Comic, User, Ad, Rating

def test_app():
    with app.app_context():
        print("Testing database connection...")
        
        # Check if tables exist
        try:
            # Test Ad model
            print("\n1. Testing Ad model...")
            ads = Ad.query.all()
            print(f"   Found {len(ads)} ads")
            
            # Test Comic model
            print("\n2. Testing Comic model...")
            comics = Comic.query.all()
            print(f"   Found {len(comics)} comics")
            
            # Test creating a test ad if none exists
            if len(ads) == 0:
                print("\n3. Creating test ad...")
                test_ad = Ad(
                    title="Test Ad",
                    ad_code="<div>Test Ad Content</div>",
                    placement="header",
                    is_active=True
                )
                db.session.add(test_ad)
                db.session.commit()
                print("   Test ad created successfully")
            
            # Test the home route data
            print("\n4. Testing home route data...")
            from app import get_featured_comics, get_trending_comics, get_top_authors, get_header_ad
            
            featured = get_featured_comics()
            print(f"   Featured comics: {len(featured)}")
            
            trending = get_trending_comics()
            print(f"   Trending comics: {len(trending)}")
            
            authors = get_top_authors()
            print(f"   Top authors: {len(authors)}")
            
            header_ad = get_header_ad()
            print(f"   Header ad: {'Found' if header_ad else 'Not found'}")
            
            print("\n✅ All tests passed!")
            
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    test_app()