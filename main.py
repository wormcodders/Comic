"""
ComicVault - Main Application Entry Point
Flask application factory and initialization
"""

from flask import Flask, render_template
from models import db
from flask_login import LoginManager
from flask_migrate import Migrate
from config import Config
from extensions import csrf, limiter
from flask_talisman import Talisman

# Initialize extensions
login_manager = LoginManager()
migrate = Migrate()

def create_app(config_class=Config):
    """Application factory pattern"""
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    
    # Security Extensions
    csrf.init_app(app)
    limiter.init_app(app)
    
    # Advanced Security Headers (CSP, HSTS)
    csp = {
        'default-src': ["'self'"],
        'script-src': ["'self'", "'unsafe-inline'", "'unsafe-eval'", "https://cdnjs.cloudflare.com", "https://cdn.jsdelivr.net", "https://code.jquery.com"],
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
        return User.query.get(int(user_id))
    
    # Register blueprints
    from routes import main as main_blueprint
    app.register_blueprint(main_blueprint)
    
    # Create database tables
    with app.app_context():
        db.create_all()
        
        # Ensure security_answer_hash column exists in SQLite user table
        try:
            with db.engine.connect() as conn:
                from sqlalchemy import text
                result = conn.execute(text("PRAGMA table_info(user)")).fetchall()
                cols = [row[1] for row in result]
                if 'security_answer_hash' not in cols:
                    conn.execute(text("ALTER TABLE user ADD COLUMN security_answer_hash VARCHAR(256)"))
                    conn.commit()
        except Exception as e:
            pass
        
        # Create default admin user if not exists
        admin_email = 'admin@comicvault.app'
        admin_user = User.query.filter((User.email == admin_email) | (User.username == 'admin')).first()
        
        if not admin_user:
            admin = User(
                username='admin',
                email=admin_email,
                is_admin=True
            )
            admin.set_password('admin123')
            admin.set_security_answer('Batman')
            db.session.add(admin)
            db.session.commit()
            print(f"OK Default admin user created ({admin_email} / admin123)")
        else:
            if not admin_user.security_answer_hash:
                admin_user.set_security_answer('Batman')
                db.session.commit()
            print(f"i Admin user already exists: {admin_user.username} ({admin_user.email})")
        
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
            print("OK Default categories created")
    
    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000)