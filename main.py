"""
ComicVault - Main Application Entry Point
Flask application factory and initialization
"""

import hmac
import os

from flask import Flask, jsonify, request, redirect, url_for
from models import db
from flask_login import LoginManager
from flask_migrate import Migrate
from config import config
from extensions import csrf, limiter
from flask_talisman import Talisman

# Initialize extensions
login_manager = LoginManager()
migrate = Migrate()

def create_app(config_class=None):
    """Application factory pattern"""
    app = Flask(__name__)
    if config_class is None:
        environment = os.environ.get('APP_ENV', os.environ.get('FLASK_ENV', 'development'))
        if environment not in config:
            raise RuntimeError(f'Unknown application environment: {environment}')
        config_class = config[environment]
    app.config.from_object(config_class)
    from app_setup import configure_security, register_admin_command
    configure_security(app)
    register_admin_command(app)
    
    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    
    # Security Extensions
    limiter.init_app(app)
    csrf.init_app(app)
    
    # Advanced Security Headers (CSP, HSTS)
    csp = {
        'default-src': ["'self'"],
        'script-src': ["'self'", "'unsafe-inline'", "https://cdnjs.cloudflare.com", "https://cdn.jsdelivr.net", "https://code.jquery.com"],
        'style-src': ["'self'", "'unsafe-inline'", "https://cdnjs.cloudflare.com", "https://cdn.jsdelivr.net", "https://fonts.googleapis.com"],
        'font-src': ["'self'", "https://cdnjs.cloudflare.com", "https://fonts.gstatic.com"],
        'img-src': ["'self'", "data:", "https:", "http:"],
        'connect-src': ["'self'", "https:", "http:"],
        'media-src': ["'self'"],
        'frame-src': ["'self'", "https:"],
    }
    
    force_https = app.config.get('SESSION_COOKIE_SECURE', False)
    
    talisman = Talisman(app, 
        content_security_policy=csp, 
        force_https=force_https,
        session_cookie_secure=force_https,
        session_cookie_http_only=True,
        session_cookie_samesite='Lax'
    )
    
    # Configure login
    login_manager.login_view = 'main.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'
    
    # Import models to register them
    from models import User, Comic, Category, Tag, ReadingProgress, Rating, UserLibrary, Ad
    
    # User loader for Flask-Login
    @login_manager.user_loader
    def load_user(user_id):
        try:
            identifier, separator, signature = str(user_id).partition(':')
            if not separator or len(identifier) > 10 or not identifier.isdecimal():
                return None
            user = db.session.get(User, int(identifier))
            if user and hmac.compare_digest(user.get_id(), str(user_id)):
                return user
        except (TypeError, ValueError, OverflowError):
            pass
        return None

    @login_manager.unauthorized_handler
    def unauthorized():
        from routes import wants_json_response
        if wants_json_response():
            return jsonify(success=False, message='Authentication required'), 401
        return redirect(url_for('main.login', next=request.full_path.rstrip('?')))
    
    # Register blueprints
    from routes import main as main_blueprint
    app.register_blueprint(main_blueprint)
    
    # Create database tables
    with app.app_context():
        db.create_all()
        
        # Compatibility with SQLite databases created before recovery answers existed.
        if db.engine.dialect.name == 'sqlite':
            with db.engine.connect() as conn:
                from sqlalchemy import text
                result = conn.execute(text("PRAGMA table_info(user)")).fetchall()
                cols = [row[1] for row in result]
                if 'security_answer_hash' not in cols:
                    conn.execute(text("ALTER TABLE user ADD COLUMN security_answer_hash VARCHAR(256)"))
                    conn.commit()

        from app_setup import create_configured_admin
        create_configured_admin()
        
        # Create default categories if empty
        if Category.query.count() == 0:
            default_categories = [
                ('Action', 'action', 'fas fa-fist-raised'),
                ('Adventure', 'adventure', 'fas fa-compass'),
                ('Comedy', 'comedy', 'fas fa-laugh'),
                ('Drama', 'drama', 'fas fa-theater-masks'),
                ('Fantasy', 'fantasy', 'fas fa-hat-wizard'),
                ('Horror', 'horror', 'fas fa-ghost'),
                ('Mystery', 'mystery', 'fas fa-search'),
                ('Romance', 'romance', 'fas fa-heart'),
                ('Sci-Fi', 'sci-fi', 'fas fa-rocket'),
                ('Slice of Life', 'slice-of-life', 'fas fa-coffee'),
            ]
            for name, slug, icon in default_categories:
                category = Category(name=name, slug=slug, icon=icon)
                db.session.add(category)
            db.session.commit()

    @app.context_processor
    def template_utilities():
        from datetime import datetime
        return {'now': datetime.utcnow()}
    
    return app


if __name__ == '__main__':
    app = create_app()
    app.run(host=os.environ.get('HOST', '127.0.0.1'), port=int(os.environ.get('PORT', '5000')))
