import os
from datetime import timedelta

class Config:
    """Base configuration"""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
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
    
    # Pagination
    COMICS_PER_PAGE = 12
    
    # AI/LLM Configuration (for Vision LLM)
    AI_API_KEY = os.environ.get('AI_API_KEY')
    AI_MODEL = 'gpt-4-vision-preview'  # or appropriate vision model
    AI_BASE_URL = os.environ.get('AI_BASE_URL')  # e.g., http://localhost:11434/v1 for Ollama
    USE_LOCAL_LLM = os.environ.get('USE_LOCAL_LLM', 'false').lower() == 'true'  # Set to 'true' for local LLMs like Ollama
    
class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    
class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    SECRET_KEY = os.environ.get('SECRET_KEY')
    SESSION_COOKIE_SECURE = True
    
class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'

# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
