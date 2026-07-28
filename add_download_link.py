"""Script to add download_link column to comic table"""
import os
import sys

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask
from models import db, Comic
from config import config

def add_download_link_column():
    """Add download_link column to Comic table"""
    app = Flask(__name__)
    app.config.from_object(config['default'])
    db.init_app(app)
    
    with app.app_context():
        # Check if column exists
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('comic')]
        
        if 'download_link' not in columns:
            print("Adding download_link column to comic table...")
            from sqlalchemy import text
            with db.engine.connect() as conn:
                conn.execute(text('ALTER TABLE comic ADD COLUMN download_link VARCHAR(1000)'))
                conn.commit()
            print("✅ Column added successfully!")
        else:
            print("✅ download_link column already exists.")

if __name__ == '__main__':
    add_download_link_column()
