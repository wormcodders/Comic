import sqlite3
import os

db_path = 'e:/Comic/instance/comics.db'
if not os.path.exists(db_path):
    print(f"Database {db_path} does not exist")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()
print(f"Tables: {tables}")

for table in tables:
    table_name = table[0]
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cursor.fetchone()[0]
        print(f"Table {table_name}: {count} rows")
    except Exception as e:
        print(f"Error reading {table_name}: {e}")

conn.close()
