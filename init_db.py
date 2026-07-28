#!/usr/bin/env python3
"""
Initialize database with all tables
"""
import sys
import io

# Fix encoding for Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Import the app and database
from app import app
from database import db
from models import User, Comic, ComicTag, Chapter, ReadingProgress, Rating, Ad, Setting

def init_database():
    with app.app_context():
        print("Creating all database tables...")
        db.create_all()
        print("SUCCESS: All tables created!")
        
        # Verify tables were created
        import sqlite3
        conn = sqlite3.connect('comicvault.db')
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        print("\nTables in database:")
        for table in tables:
            print(f"  - {table[0]}")
        conn.close()

if __name__ == '__main__':
    init_database()
