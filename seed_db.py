"""Script to seed the database with sample data including default ads"""
from database import seed_sample_data

if __name__ == '__main__':
    seed_sample_data()
    print("Database seeded successfully!")
