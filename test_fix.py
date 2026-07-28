"""Test the visibility fix"""
import sys
sys.path.insert(0, 'E:\\Comic')

from models import Comic

print("Comic model loaded successfully")
print(f"Has visibility attribute: {hasattr(Comic, 'visibility')}")

# Test querying
from app import app
with app.app_context():
    try:
        featured = Comic.query.filter_by(visibility='public').limit(5).all()
        print(f"Query successful! Found {len(featured)} public comics")
    except Exception as e:
        print(f"Query failed: {e}")
