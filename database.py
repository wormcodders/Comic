"""Database initialization and utility functions"""

from flask import Flask
from models import db, User, Comic, ComicTag, ReadingProgress, Rating, Ad, Setting
from config import config
import os

def create_app(config_name='default'):
    """Create Flask app with database"""
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    
    # Initialize database
    db.init_app(app)
    
    return app

def init_db(app=None):
    """Initialize database with tables"""
    if app is None:
        app = create_app()
    
    with app.app_context():
        # Create all tables
        db.create_all()
        
        # Initialize default settings
        init_default_settings()
        
        # Create default admin user if none exists
        create_default_admin()
        
        # Create upload directories
        create_upload_directories()
        
        print("Database initialized successfully!")

def init_default_settings():
    """Initialize default settings in database"""
    defaults = [
        ('llm_base_url', '', 'Base URL for LLM API (OpenAI compatible)'),
        ('llm_api_key', '', 'API Key for LLM (optional)'),
        ('llm_model', 'koboldcpp/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-Q8_0', 'Model name for LLM'),
        ('llm_temperature', '0.7', 'Temperature for generation (0.0-2.0)'),
        ('llm_max_tokens', '4096', 'Max tokens for LLM response'),
        ('upfiles_endpoint', 'https://api.upfiles.com/upload', 'UpFiles API endpoint'),
        ('upfiles_token', '', 'UpFiles API authentication token'),
        ('upfiles_folder_alias', '', 'UpFiles folder alias (optional)'),
        ('site_name', 'ComicVault', 'Site name'),
        ('site_description', '', 'Site description'),
        ('items_per_page', '12', 'Number of items per page'),
        ('maintenance_mode', '0', 'Maintenance mode (0=off, 1=on)'),
        ('cloud_storage_enabled', '0', 'Enable Catbox.moe cloud storage (0=off, 1=on)'),
        ('catbox_userhash', '', 'Catbox.moe account userhash (optional)'),
    ]
    
    for key, value, description in defaults:
        if not Setting.query.filter_by(key=key).first():
            Setting.set(key, value, description)
            print(f"Initialized setting: {key}")

def create_default_admin():
    """Create default admin user if none exists"""
    if not User.query.filter_by(is_admin=True).first():
        admin = User(
            username='admin',
            email='admin@comics.com',
            is_admin=True
        )
        admin.set_password('admin123')  # Change in production
        db.session.add(admin)
        db.session.commit()
        print("Created default admin user: admin/admin123")

def create_upload_directories():
    """Create necessary upload directories"""
    from config import Config
    
    directories = [
        Config.UPLOAD_FOLDER,
        Config.COMIC_UPLOAD_FOLDER,
        Config.COVER_UPLOAD_FOLDER
    ]
    
    for directory in directories:
        if not os.path.exists(directory):
            os.makedirs(directory)
            print(f"Created directory: {directory}")

def reset_db():
    """Reset database (drop and recreate all tables)"""
    app = create_app()
    
    with app.app_context():
        db.drop_all()
        db.create_all()
        init_default_settings()
        create_default_admin()
        create_upload_directories()
        print("Database reset successfully!")

def get_sample_comics():
    """Get sample comics for testing"""
    return [
        {
            'title': 'The Amazing Spider-Man',
            'author': 'Stan Lee',
            'category': 'Superheroes',
            'genre': 'Action',
            'tags': ['superheroes', 'marvel', 'action'],
            'description': 'The classic adventures of Spider-Man!',
            'cover_image': '/static/covers/spiderman.jpg'
        },
        {
            'title': 'Batman: The Dark Knight',
            'author': 'Frank Miller',
            'category': 'Superheroes',
            'genre': 'Dark',
            'tags': ['superheroes', 'dc', 'dark'],
            'description': 'The dark and gritty Batman story.',
            'cover_image': '/static/covers/batman.jpg'
        },
        {
            'title': 'Manga Collection Vol. 1',
            'author': 'Various',
            'category': 'Manga',
            'genre': 'Mixed',
            'tags': ['manga', 'japanese', 'collection'],
            'description': 'A collection of popular manga series.',
            'cover_image': '/static/covers/manga1.jpg'
        },
        {
            'title': 'Sci-Fi Chronicles',
            'author': 'Isaac Asimov',
            'category': 'Sci-Fi',
            'genre': 'Science Fiction',
            'tags': ['scifi', 'space', 'future'],
            'description': 'Epic science fiction stories.',
            'cover_image': '/static/covers/scifi.jpg'
        },
        {
            'title': 'Fantasy Realms',
            'author': 'Tolkien',
            'category': 'Fantasy',
            'genre': 'High Fantasy',
            'tags': ['fantasy', 'magic', 'dragons'],
            'description': 'Magical worlds and epic quests.',
            'cover_image': '/static/covers/fantasy.jpg'
        },
        {
            'title': 'Comedy Central',
            'author': 'Various',
            'category': 'Comedy',
            'genre': 'Humor',
            'tags': ['comedy', 'funny', 'slice-of-life'],
            'description': 'Laugh-out-loud comic strips.',
            'cover_image': '/static/covers/comedy.jpg'
        }
    ]

def seed_db():
    """Seed database with sample data"""
    from flask import Flask
    from config import config
    
    app = Flask(__name__)
    app.config.from_object(config['default'])
    db.init_app(app)
    
    with app.app_context():
        # Check if data already exists
        if Comic.query.first():
            print("Database already has data, skipping seed")
            return
        
        # Add sample comics
        comics = get_sample_comics()
        for comic_data in comics:
            comic = Comic(
                title=comic_data['title'],
                author=comic_data['author'],
                category=comic_data['category'],
                description=comic_data['description'],
                cover_image=comic_data['cover_image'],
                is_published=True
            )
            db.session.add(comic)
            db.session.flush()  # Get the comic ID
            
            # Add tags
            for tag_name in comic_data['tags']:
                tag = ComicTag(comic_id=comic.id, tag=tag_name)
                db.session.add(tag)
        
        # Add sample ads with banner_link support
        ads = [
            {
                'title': 'Header Banner Ad',
                'ad_code': '',
                'banner_link': '',
                'target_url': '',
                'placement': 'header',
                'ad_type': 'banner',
                'is_active': False
            },
            {
                'title': 'Sidebar Ad',
                'ad_code': '',
                'banner_link': '',
                'target_url': '',
                'placement': 'sidebar',
                'ad_type': 'banner',
                'is_active': False
            },
            {
                'title': 'Footer Banner Ad',
                'ad_code': '',
                'banner_link': '',
                'target_url': '',
                'placement': 'footer',
                'ad_type': 'banner',
                'is_active': False
            },
            {
                'title': 'Comic Detail Page Ad',
                'ad_code': '',
                'banner_link': '',
                'target_url': '',
                'placement': 'comic-detail',
                'ad_type': 'banner',
                'is_active': False
            }
        ]
        
        for ad_data in ads:
            ad = Ad(
                title=ad_data['title'],
                ad_code=ad_data['ad_code'],
                banner_link=ad_data['banner_link'],
                target_url=ad_data['target_url'],
                placement=ad_data['placement'],
                ad_type=ad_data['ad_type'],
                is_active=ad_data['is_active']
            )
            db.session.add(ad)
        
        db.session.commit()
        print("Sample data seeded successfully!")
