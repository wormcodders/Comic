#!/usr/bin/env python3
"""
Fix database schema - add missing 'name' column to ad table
"""
import sqlite3
import os
import sys

# Fix encoding for Windows
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

DB_PATH = 'comicvault.db'

def check_and_fix_ad_table():
    """Check if ad table has 'name' column and add it if missing"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check current schema
    cursor.execute("PRAGMA table_info(ad)")
    columns = cursor.fetchall()
    
    print("Current 'ad' table columns:")
    column_names = []
    for col in columns:
        print(f"  - {col[1]} ({col[2]})")
        column_names.append(col[1])
    
    # Check if 'name' column exists
    if 'name' not in column_names:
        print("\nWARNING: 'name' column is missing! Adding it now...")
        
        # Add the name column
        cursor.execute("ALTER TABLE ad ADD COLUMN name VARCHAR(100)")
        conn.commit()
        print("SUCCESS: Added 'name' column to ad table")
        
        # Verify the fix
        cursor.execute("PRAGMA table_info(ad)")
        columns = cursor.fetchall()
        print("\nUpdated 'ad' table columns:")
        for col in columns:
            print(f"  - {col[1]} ({col[2]})")
    else:
        print("\nSUCCESS: 'name' column already exists")
    
    conn.close()

if __name__ == '__main__':
    check_and_fix_ad_table()
