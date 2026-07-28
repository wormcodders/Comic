"""Verify download_link column exists"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask
from models import db
from config import config
from sqlalchemy import inspect

app = Flask(__name__)
app.config.from_object(config['default'])
db.init_app(app)

with app.app_context():
    inspector = inspect(db.engine)
    columns = [col['name'] for col in inspector.get_columns('comic')]
    print("Comic table columns:")
    for col in columns:
        print(f"  - {col}")
    
    if 'download_link' in columns:
        print("\n[SUCCESS] download_link column exists!")
    else:
        print("\n[ERROR] download_link column NOT found!")
