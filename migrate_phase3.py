"""
Database Migration Script for Phase 3: Social Features
Run this script to create the new tables for comments, reading lists, activity feed, and follows.
"""

import sys
import os

# Add the project directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from models import db, Comment, CommentLike, ReadingList, ReadingListItem, Activity, Follow
from config import Config

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)
    return app

def migrate():
    app = create_app()
    
    with app.app_context():
        print("Creating Phase 3 tables...")
        
        # Create all tables
        db.create_all()
        
        print("✅ Phase 3 tables created successfully!")
        print("\nTables created:")
        print("  - comment")
        print("  - comment_like")
        print("  - reading_list")
        print("  - reading_list_item")
        print("  - activity")
        print("  - follow")
        print("\nMigration complete!")

if __name__ == '__main__':
    migrate()
