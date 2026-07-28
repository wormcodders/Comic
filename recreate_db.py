#!/usr/bin/env python3
"""
Recreate database with correct schema
"""
import os
import sys

os.chdir(r'E:\Comic')
sys.path.insert(0, r'E:\Comic')

# Remove existing database
if os.path.exists('comics.db'):
    os.remove('comics.db')
    print("Removed old comics.db")

from app import create_app
from models import db, User, Comic, ComicTag, Chapter, ReadingProgress, Rating, Ad, Setting

app = create_app('development')

with app.app_context():
    print("Creating database tables...")
    db.create_all()
    print("SUCCESS: Database tables created!")
    
    # Verify tables
    from sqlalchemy import inspect
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    print(f"\nCreated {len(tables)} tables:")
    for table in tables:
        print(f"  - {table}")
    
    # Check ad table columns
    print("\nAd table columns:")
    columns = inspector.get_columns('ad')
    for col in columns:
        print(f"  - {col['name']}: {col['type']}")
