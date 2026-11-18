import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

class Config:
    """Base configuration"""
    SECRET_KEY = os.environ.get('SECRET_KEY')
    CREDENTIAL_ENCRYPTION_KEY = os.environ.get('CREDENTIAL_ENCRYPTION_KEY')
    ENV_NAME = 'development'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///comics.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # File upload configuration
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB max file size
    
    # Comic storage paths
    COMIC_UPLOAD_FOLDER = os.path.join(UPLOAD_FOLDER, 'comics')
    COVER_UPLOAD_FOLDER = os.path.join(UPLOAD_FOLDER, 'covers')
    
    # Session configuration
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = False  # Overridden in ProductionConfig
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_SECURE = False
    RATELIMIT_STORAGE_URI = os.environ.get('RATELIMIT_STORAGE_URI') or 'memory://'
    REMEMBER_COOKIE_DURATION = timedelta(days=7)
    MAX_COMIC_PAGES = 500

    # An administrator is bootstrapped only when all three values are supplied.
    ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME')
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD')
    
    # Pagination
    COMICS_PER_PAGE = 12
    
    # AI/LLM Configuration (for Vision LLM)
    AI_API_KEY = os.environ.get('AI_API_KEY')
    AI_MODEL = 'gpt-4-vision-preview'  # or appropriate vision model
    AI_BASE_URL = os.environ.get('AI_BASE_URL')  # e.g., http://localhost:11434/v1 for Ollama
    USE_LOCAL_LLM = os.environ.get('USE_LOCAL_LLM', 'false').lower() == 'true'  # Set to 'true' for local LLMs like Ollama
    
class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = os.environ.get('FLASK_DEBUG', 'false').lower() in ('1', 'true')
    
class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    ENV_NAME = 'production'
    SECRET_KEY = os.environ.get('SECRET_KEY')
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'true').lower() in ('1', 'true')
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    RATELIMIT_STORAGE_URI = os.environ.get('RATELIMIT_STORAGE_URI')
    
class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    ENV_NAME = 'testing'
    SECRET_KEY = 'isolated-testing-key-never-use-in-production'
    ADMIN_USERNAME = ADMIN_EMAIL = ADMIN_PASSWORD = None
    RATELIMIT_ENABLED = False
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'

# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
