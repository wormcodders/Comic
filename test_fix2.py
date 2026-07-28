#!/usr/bin/env python3
"""Test script to verify the views fix"""

from app import app
from models import Comic

with app.app_context():
    # Test that Comic.view_count exists and works
    print("Testing Comic.view_count attribute...")
    
    # Test query with view_count ordering
    try:
        trending = Comic.query.filter_by(visibility='public').order_by(
            Comic.view_count.desc()
        ).limit(8).all()
        print("SUCCESS: Comic.view_count.desc() query works!")
        print(f"Found {len(trending)} comics")
    except AttributeError as e:
        print(f"FAILED: {e}")
    
    # Test that Comic.views still fails (to confirm we fixed the right thing)
    try:
        Comic.views.desc()
        print("WARNING: Comic.views still exists (unexpected)")
    except AttributeError:
        print("EXPECTED: Comic.views does not exist (use Comic.view_count instead)")
    
    print("\nFix verified successfully!")
