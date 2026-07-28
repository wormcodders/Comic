#!/usr/bin/env python3
"""
Verify database tables
"""
import sys
import io
import sqlite3

# Fix encoding for Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

DB_PATH = 'comicvault.db'

def verify_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    
    print(f"Found {len(tables)} tables:")
    for table in tables:
        print(f"  - {table[0]}")
    
    # Check ad table schema specifically
    print("\nChecking 'ad' table schema:")
    cursor.execute("PRAGMA table_info(ad)")
    columns = cursor.fetchall()
    for col in columns:
        print(f"  - {col[1]}: {col[2]}")
    
    conn.close()
    print("\nDatabase verification complete!")

if __name__ == '__main__':
    verify_database()
