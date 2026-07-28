
import os
import sys

# Add project root to sys.path BEFORE any local imports
sys.path.insert(0, r'e:\Comic')

from app import create_app
from models import db, User

app = create_app()

with app.app_context():
    users = User.query.all()
    print(f"Total users: {len(users)}")
    for user in users:
        print(f"ID: {user.id}, Username: {user.username}, Email: {user.email}, Admin: {user.is_admin}")
