"""Add language column to comic table"""
import sqlite3
import os

# Path to the database (in instance folder)
db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'comics.db')

print(f"Connecting to database: {db_path}")

if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check if language column exists
    cursor.execute("PRAGMA table_info(comic)")
    columns = [column[1] for column in cursor.fetchall()]
    print(f"Current columns: {columns}")

    if 'language' not in columns:
        print("Adding 'language' column to comic table...")
        cursor.execute("ALTER TABLE comic ADD COLUMN language VARCHAR(50) DEFAULT 'English'")
        conn.commit()
        print("Column added successfully!")
    else:
        print("Column 'language' already exists.")

    conn.close()
else:
    print(f"Database not found at {db_path}")

# Also check root level comicvault.db and comics.db if they exist
for db_name in ['comicvault.db', 'comics.db']:
    root_db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), db_name)
    if os.path.exists(root_db_path):
        print(f"Connecting to root database: {root_db_path}")
        conn = sqlite3.connect(root_db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(comic)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'language' not in columns:
            print(f"Adding 'language' column to comic table in {db_name}...")
            cursor.execute("ALTER TABLE comic ADD COLUMN language VARCHAR(50) DEFAULT 'English'")
            conn.commit()
            print("Column added successfully!")
        conn.close()

print("Database update complete!")
