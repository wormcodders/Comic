import os
from app import app, db
from sqlalchemy import text

def fix_schema():
    with app.app_context():
        # Tables and columns to check
        schema_updates = {
            'chapter': [
                ('pdf_file', 'VARCHAR(500)'),
                ('page_count', 'INTEGER DEFAULT 0')
            ],
            'reading_progress': [
                ('current_page', 'INTEGER DEFAULT 0'),
                ('total_pages', 'INTEGER DEFAULT 0'),
                ('percentage', 'FLOAT DEFAULT 0.0'),
                ('last_read', 'DATETIME')
            ]
        }
        
        for table, columns in schema_updates.items():
            for col_name, col_type in columns:
                try:
                    db.session.execute(text(f"SELECT {col_name} FROM {table} LIMIT 1"))
                    print(f"Column '{table}.{col_name}' already exists.")
                except Exception:
                    print(f"Adding '{table}.{col_name}' column...")
                    try:
                        db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"))
                        db.session.commit()
                        print(f"Successfully added '{table}.{col_name}'.")
                    except Exception as e:
                        print(f"Error adding {table}.{col_name}: {e}")

if __name__ == "__main__":
    fix_schema()
