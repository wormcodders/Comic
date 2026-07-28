"""Add visibility column to comic table"""
import sqlite3
import os

# Path to the database (in instance folder)
db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'comics.db')

print(f"Connecting to database: {db_path}")

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Check if visibility column exists
cursor.execute("PRAGMA table_info(comic)")
columns = [column[1] for column in cursor.fetchall()]
print(f"Current columns: {columns}")

if 'visibility' not in columns:
    print("Adding 'visibility' column to comic table...")
    cursor.execute("ALTER TABLE comic ADD COLUMN visibility VARCHAR(20) DEFAULT 'public'")
    conn.commit()
    print("Column added successfully!")
else:
    print("Column 'visibility' already exists.")

conn.close()
print("Database update complete!")
