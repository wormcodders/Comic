"""Main Flask application for Comics Collection App"""

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
import os
import shutil
from datetime import datetime
from config import config
from extensions import csrf, limiter
from models import db, User, Comic, ComicTag, ReadingProgress, Rating, Ad, Chapter
from database import init_db, create_upload_directories

# Import and register blueprint
from routes import main as main_blueprint


def create_app(config_name='default'):
    """Create and configure Flask application"""
    app = Flask(__name__)
    
    # Load configuration
    app.config.from_object(config[config_name])
    
    # Initialize extensions
    db.init_app(app)
    
    # Security Extensions
    csrf.init_app(app)
    
    # Rate Limiting
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
    
    # Setup login manager
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    login_manager.login_message = 'Please log in to access this page.'
    
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
    
    # Register blueprint
    app.register_blueprint(main_blueprint)
    
    # Create upload directories
    create_upload_directories()
    
    # Context processor to make active ads available in all templates
    @app.context_processor
    def inject_active_ads():
        """Inject active ads into all templates"""
        active_ads_list = Ad.query.filter_by(is_active=True).all()
        active_ads_dict = {ad.placement: ad for ad in active_ads_list}
        return {'active_ads': active_ads_dict}
    
    # Helper functions
    def allowed_file(filename, allowed_extensions):
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions
    
    # ===== ROUTES =====
    @app.route('/')
    def home():
        # Get featured comics (those with is_featured=True)
        featured = Comic.query.filter_by(is_featured=True).limit(12).all()
        
        # Get trending comics (most viewed)
        trending = Comic.query.order_by(Comic.view_count.desc()).limit(12).all()
        
        # Get recent comics (newest additions)
        recent = Comic.query.order_by(Comic.created_at.desc()).limit(12).all()
        
        # Get unique tags for categories (from ComicTag)
        tags = db.session.query(ComicTag.tag).distinct().all()
        categories = [{'slug': tag[0], 'name': tag[0].title(), 'icon': '📚'} for tag in tags]
        # Group comics by category for the category sections
        comics_by_category = {}
        for category in categories:
            category_comics = Comic.query.join(ComicTag).filter(
                ComicTag.tag == category['slug']
            ).limit(6).all()
            comics_by_category[category['slug']] = category_comics
        
        return render_template('home.html',
                             featured=featured,
                             trending=trending,
                             recent=recent,
                             categories=categories,
                             comics_by_category=comics_by_category)
    
    @app.route('/categories')
    def categories():
        """List all categories"""
        categories_db = Category.query.all()
        categories = []
        for cat in categories_db:
            count = Comic.query.filter_by(is_published=True, category=cat.name).count()
            if count > 0:
                categories.append({
                    'slug': cat.slug,
                    'name': cat.name,
                    'count': count,
                    'icon': cat.icon if cat.icon else 'fas fa-book'
                })
        
        # Sort by count descending
        categories = sorted(categories, key=lambda x: x['count'], reverse=True)
        
        return render_template('categories.html', categories=categories)
    
    @app.route('/category/<slug>')
    def category_view(slug):
        """Browse comics by category"""
        page = request.args.get('page', 1, type=int)
        
        # Get category object
        category = Category.query.filter_by(slug=slug).first_or_404()
        
        comics = Comic.query.filter_by(is_published=True)\
            .filter(Comic.category == category.name)\
            .order_by(Comic.created_at.desc())\
            .paginate(page=page, per_page=12, error_out=False)
        
        return render_template('category.html',
                             comics=comics,
                             category=category)
    
    @app.route('/trending')
    def trending():
        """Trending comics page"""
        page = request.args.get('page', 1, type=int)
        comics = Comic.query.order_by(Comic.view_count.desc())\
                      .paginate(page=page, per_page=12, error_out=False)
        return render_template('trending.html', comics=comics)
    
    @app.route('/comic/<int:comic_id>')
    def comic_detail(comic_id):
        """View comic details"""
        comic = Comic.query.get_or_404(comic_id)
        
        # Increment view count
        comic.view_count += 1
        db.session.commit()
        
        # Get user's rating if logged in
        user_rating = None
        if current_user.is_authenticated:
            user_rating = Rating.query.filter_by(
                user_id=current_user.id,
                comic_id=comic_id
            ).first()
        
        # Get user's reading progress if logged in
        user_progress = None
        if current_user.is_authenticated:
            user_progress = ReadingProgress.query.filter_by(
                user_id=current_user.id,
                comic_id=comic_id
            ).first()
        
        return render_template('comic_detail.html',
                             comic=comic,
                             user_rating=user_rating,
                             user_progress=user_progress)
    
    @app.route('/read/<int:id>')
    @login_required
    def read_comic(id):
        """Read comic online"""
        comic = Comic.query.get_or_404(id)
        
        if not comic.pdf_file:
            flash('This comic is not available for online reading.', 'error')
            return redirect(url_for('comic_detail', id=id))
        
        # Get or create reading progress
        progress = ReadingProgress.query.filter_by(
            user_id=current_user.id,
            comic_id=id
        ).first()
        
        if not progress:
            progress = ReadingProgress(
                user_id=current_user.id,
                comic_id=id,
                current_page=1,
                total_pages=0
            )
            db.session.add(progress)
            db.session.commit()
        
        return render_template('reader.html',
                             comic=comic,
                             current_page=progress.current_page)
    
    @app.route('/library')
    @login_required
    def library():
        """User personal library"""
        page = request.args.get('page', 1, type=int)
        
        # Get comics with reading progress - use subquery to get just Comic objects
        reading_progress_subq = db.session.query(ReadingProgress.comic_id).filter(
            ReadingProgress.user_id == current_user.id
        ).subquery()
        
        comics = Comic.query.filter(
            Comic.id.in_(reading_progress_subq)
        ).order_by(Comic.created_at.desc())\
            .paginate(page=page, per_page=12, error_out=False)
        
        return render_template('library.html', comics=comics)
    
    @app.route('/favorites')
    @login_required
    def favorites():
        """User favorite comics"""
        page = request.args.get('page', 1, type=int)
        
        # Get comics with high ratings (4+ stars)
        comics = db.session.query(Comic, Rating)\
            .join(Rating, Comic.id == Rating.comic_id)\
            .filter(Rating.user_id == current_user.id, Rating.score >= 4)\
            .order_by(Rating.score.desc())\
            .paginate(page=page, per_page=12, error_out=False)
        
        return render_template('favorites.html', comics=comics)
    
    @app.route('/search')
    def search():
        """Search comics"""
        query = request.args.get('q', '')
        page = request.args.get('page', 1, type=int)
        
        if query:
            comics = Comic.query.filter_by(is_published=True)\
                .filter(Comic.title.ilike(f'%{query}%'))\
                .paginate(page=page, per_page=12, error_out=False)
        else:
            comics = None
        
        return render_template('search.html',
                             query=query,
                             comics=comics)
    
    # ===== AUTHENTICATION ROUTES =====
    @app.route('/auth/login', methods=['GET', 'POST'])
    def login():
        """User login"""
        if current_user.is_authenticated:
            return redirect(url_for('home'))
        
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            
            # Try to find user by username or email
            user = User.query.filter_by(username=username).first()
            if not user:
                user = User.query.filter_by(email=username).first()
            
            if user and user.check_password(password):
                login_user(user, remember=request.form.get('remember') == 'on')
                flash(f'Welcome back, {user.username}! Login successful.', 'success')
                next_page = request.args.get('next')
                
                # Redirect admin users to admin dashboard
                if user.is_admin and not next_page:
                    return redirect(url_for('admin_dashboard'))
                
                return redirect(next_page) if next_page else redirect(url_for('home'))
            else:
                flash('Invalid username/email or password. Please try again.', 'error')
        
        return render_template('auth/login.html')
    @app.route('/auth/register', methods=['GET', 'POST'])
    def register():
        """User registration"""
        if current_user.is_authenticated:
            return redirect(url_for('home'))
        
        if request.method == 'POST':
            username = request.form.get('username')
            email = request.form.get('email')
            password = request.form.get('password')
            
            # Check if user exists
            if User.query.filter_by(username=username).first():
                flash('Username already exists', 'error')
                return render_template('auth/register.html')
            
            if User.query.filter_by(email=email).first():
                flash('Email already registered', 'error')
                return render_template('auth/register.html')
            
            # Create new user
            user = User(username=username, email=email)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))
        
        return render_template('auth/register.html')
    
    @app.route('/auth/logout')
    @login_required
    def logout():
        """User logout"""
        logout_user()
        flash('You have been logged out.', 'info')
        return redirect(url_for('home'))
    
    # ===== ADMIN ROUTES =====
    @app.route('/admin')
    @login_required
    def admin_dashboard():
        """Admin dashboard"""
        if not current_user.is_admin:
            return redirect(url_for('home'))
        
        # Get statistics
        stats = {
            'total_comics': Comic.query.count(),
            'total_users': User.query.count(),
            'total_ratings': Rating.query.count(),
            'total_categories': ComicTag.query.with_entities(ComicTag.tag).distinct().count()
        }
        
        # Recent comics
        recent_comics = Comic.query.order_by(Comic.created_at.desc())\
                                 .limit(5).all()
        
        return render_template('admin/admin_dashboard.html',
                             stats=stats,
                             recent_comics=recent_comics)

    @app.route('/admin/analytics')
    @login_required
    def admin_analytics():
        """Admin analytics dashboard"""
        if not current_user.is_admin:
            return redirect(url_for('home'))
        
        # Get analytics statistics
        from datetime import datetime, timedelta
        
        # Calculate avg reading time
        total_time_records = db.session.query(ReadingProgress.total_time_spent).filter(ReadingProgress.total_time_spent > 0).all()
        avg_time_seconds = 0
        if total_time_records:
            avg_time_seconds = sum(r[0] for r in total_time_records) / len(total_time_records)
            
        hours = int(avg_time_seconds // 3600)
        minutes = int((avg_time_seconds % 3600) // 60)
        avg_reading_time_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
        
        # Basic stats
        stats = {
            'total_comics': Comic.query.count(),
            'total_users': User.query.count(),
            'total_ratings': Rating.query.count(),
            'total_views': db.session.query(db.func.sum(Comic.view_count)).scalar() or 0,
            'avg_reading_time': avg_reading_time_str
        }
        
        # Recent activity (last 30 days)
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        recent_activity = {
            'new_users': User.query.filter(User.created_at >= thirty_days_ago).count(),
            'new_comics': Comic.query.filter(Comic.created_at >= thirty_days_ago).count(),
            'new_ratings': Rating.query.filter(Rating.created_at >= thirty_days_ago).count(),
        }
        
        # Top rated comics
        top_comics = Comic.query.filter(Comic.average_rating > 0)\
                               .order_by(Comic.average_rating.desc())\
                               .limit(10).all()
        
        # Most viewed comics
        most_viewed = Comic.query.order_by(Comic.view_count.desc())\
                                .limit(10).all()
                                
        # ==== CHART DATA CALCULATION ====
        import json
        now = datetime.utcnow()
        
        # 1. User Growth (Last 6 Months)
        user_growth_labels = []
        user_growth_data = []
        for i in range(5, -1, -1):
            month_date = now - timedelta(days=30 * i)
            start_date = datetime(month_date.year, month_date.month, 1)
            if month_date.month == 12:
                end_date = datetime(month_date.year + 1, 1, 1)
            else:
                end_date = datetime(month_date.year, month_date.month + 1, 1)
            count = User.query.filter(User.created_at >= start_date, User.created_at < end_date).count()
            user_growth_labels.append(month_date.strftime('%b %Y'))
            user_growth_data.append(count)
            
        chart_data_user = {'labels': user_growth_labels, 'data': user_growth_data}
        
        # 2. Category Distribution
        categories_db = db.session.query(Comic.category, db.func.count(Comic.id)).filter(Comic.is_published==True).group_by(Comic.category).all()
        chart_data_category = {
            'labels': [c[0] for c in categories_db if c[0]],
            'data': [c[1] for c in categories_db if c[0]]
        }
        
        # 3. Reading Activity (Last 7 Days)
        reading_labels = []
        reading_data = []
        for i in range(6, -1, -1):
            day_date = now - timedelta(days=i)
            start = day_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end = day_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            time_sec = db.session.query(db.func.sum(ReadingProgress.total_time_spent)).filter(
                ReadingProgress.last_read_at >= start,
                ReadingProgress.last_read_at <= end
            ).scalar() or 0
            
            reading_labels.append(day_date.strftime('%a'))
            reading_data.append(round(time_sec / 3600.0, 1)) # converting to hours
        chart_data_reading = {'labels': reading_labels, 'data': reading_data}
        
        # 4. Rating Distribution (1-5 stars)
        chart_data_rating = {
            'labels': ['1 Star', '2 Stars', '3 Stars', '4 Stars', '5 Stars'],
            'data': [
                Rating.query.filter_by(score=1).count(),
                Rating.query.filter_by(score=2).count(),
                Rating.query.filter_by(score=3).count(),
                Rating.query.filter_by(score=4).count(),
                Rating.query.filter_by(score=5).count()
            ]
        }
        
        return render_template('admin/admin_analytics.html',
                             stats=stats,
                             recent_activity=recent_activity,
                             top_comics=top_comics,
                             most_viewed=most_viewed,
                             chart_data_user=json.dumps(chart_data_user),
                             chart_data_category=json.dumps(chart_data_category),
                             chart_data_reading=json.dumps(chart_data_reading),
                             chart_data_rating=json.dumps(chart_data_rating))
    @app.route('/admin/comics')
    @login_required
    def admin_comics():
        """Admin comic management"""
        if not current_user.is_admin:
            return redirect(url_for('home'))
        
        page = request.args.get('page', 1, type=int)
        status = request.args.get('status', '')
        
        query = Comic.query
        
        if status == 'published':
            query = query.filter_by(is_published=True)
        elif status == 'draft':
            query = query.filter_by(is_published=False)
        
        comics = query.order_by(Comic.created_at.desc())\
                     .paginate(page=page, per_page=20, error_out=False)
        
        return render_template('admin/comics.html', comics=comics)
    
    @app.route('/admin/comics/new', methods=['GET', 'POST'])
    @login_required
    def admin_comic_create():
        """Create new comic"""
        if not current_user.is_admin:
            return redirect(url_for('home'))
        if request.method == 'POST':
            comic = Comic(
                title=request.form.get('title'),
                description=request.form.get('description'),
                author=request.form.get('author'),
                artist=request.form.get('artist'),
                episode=request.form.get('episode'),
                category=request.form.get('category', 'General'),
                download_link=request.form.get('download_link'),  # External download URL from upload host
                uploader_id=current_user.id,
                is_published=request.form.get('is_published') == 'on'
            )
            # Handle cover upload
            if 'cover' in request.files:
                file = request.files['cover']
                if file and file.filename and allowed_file(file.filename, config['default'].ALLOWED_EXTENSIONS):
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], 'covers', filename))
                    comic.cover_image = filename
            
            # Handle PDF upload
            if 'pdf' in request.files:
                file = request.files['pdf']
                if file and file.filename and file.filename.endswith('.pdf'):
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], 'pdfs', filename))
                    comic.pdf_file = filename
            
            db.session.add(comic)
            db.session.flush()  # Get the comic ID
            
            # Add tags
            tags = request.form.get('tags')
            if tags:
                for tag_name in tags.split(','):
                    tag_name = tag_name.strip()
                    if tag_name:
                        tag = ComicTag(comic_id=comic.id, tag=tag_name)
                        db.session.add(tag)
            
            db.session.commit()
            flash('Comic created successfully!', 'success')
            return redirect(url_for('admin_comics'))
        
        # Get categories for dropdown
        categories = ['Action', 'Adventure', 'Comedy', 'Drama', 'Fantasy', 'Horror', 'Mystery', 
                     'Romance', 'Sci-Fi', 'Slice of Life', 'Sports', 'Superhero', 'Thriller']
        return render_template('admin/admin_add_comic.html', comic=None, categories=categories)
    
    @app.route('/admin/comics/<int:id>/edit', methods=['GET', 'POST'])
    @login_required
    def admin_comic_edit(id):
        """Edit comic"""
        if not current_user.is_admin:
            return redirect(url_for('home'))
        
        comic = Comic.query.get_or_404(id)
        
        if request.method == 'POST':
            # Update comic
            comic.title = request.form.get('title')
            comic.description = request.form.get('description')
            comic.author = request.form.get('author')
            comic.publisher = request.form.get('publisher')
            comic.publication_date = datetime.strptime(request.form.get('publication_date'), '%Y-%m-%d').date() if request.form.get('publication_date') else None
            comic.isbn = request.form.get('isbn')
            comic.pages = int(request.form.get('pages', 0)) if request.form.get('pages') else None
            comic.episode = request.form.get('episode')
            comic.language = request.form.get('language', 'en')
            comic.original_language = request.form.get('original_language', 'en')
            comic.status = request.form.get('status', 'active')
            comic.is_published = request.form.get('is_published') == 'on'
            if request.form.get('download_link') is not None:
                comic.download_link = request.form.get('download_link')
            
            # Handle cover upload
            if 'cover' in request.files:
                file = request.files['cover']
                if file and file.filename and allowed_file(file.filename, config['default'].ALLOWED_EXTENSIONS):
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], 'covers', filename))
                    comic.cover_image = filename
            
            # Handle PDF upload
            if 'pdf' in request.files:
                file = request.files['pdf']
                if file and file.filename and file.filename.endswith('.pdf'):
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], 'pdfs', filename))
                    comic.pdf_file = filename
            
            # Update tags
            ComicTag.query.filter_by(comic_id=id).delete()
            tags = request.form.get('tags')
            if tags:
                for tag_name in tags.split(','):
                    tag_name = tag_name.strip()
                    if tag_name:
                        tag = ComicTag(comic_id=comic.id, tag=tag_name)
                        db.session.add(tag)
            
            db.session.commit()
            flash('Comic updated successfully!', 'success')
            return redirect(url_for('admin_comics'))
        
        return render_template('admin/comic_form.html', comic=comic)
    
    @app.route('/admin/comics/<int:id>/delete', methods=['POST'])
    @login_required
    def admin_comic_delete(id):
        """Delete comic"""
        if not current_user.is_admin:
            return redirect(url_for('home'))
        
        comic = Comic.query.get_or_404(id)
        db.session.delete(comic)
        db.session.commit()
        flash('Comic deleted successfully!', 'success')
        return redirect(url_for('admin_comics'))
    
    @app.route('/admin/comics/<int:comic_id>/chapters')
    @login_required
    def admin_chapters(comic_id):
        """Admin chapters management for a comic"""
        if not current_user.is_admin:
            return redirect(url_for('home'))
        
        comic = Comic.query.get_or_404(comic_id)
        chapters = Chapter.query.filter_by(comic_id=comic_id).order_by(Chapter.chapter_number).all()
        return render_template('admin/chapters.html', comic=comic, chapters=chapters)
    
    @app.route('/admin/users')
    @login_required
    def admin_users():
        """Admin user management"""
        if not current_user.is_admin:
            return redirect(url_for('home'))
        
        page = request.args.get('page', 1, type=int)
        search = request.args.get('search', '')
        role = request.args.get('role', '')
        
        query = User.query
        
        if search:
            query = query.filter(
                (User.username.ilike(f'%{search}%')) |
                (User.email.ilike(f'%{search}%'))
            )
        if role == 'admin':
            query = query.filter_by(is_admin=True)
        elif role == 'user':
            query = query.filter_by(is_admin=False)
        
        users = query.order_by(User.created_at.desc())\
                        .paginate(page=page, per_page=20, error_out=False)
        
        return render_template('admin/users.html', users=users)
    
    @app.route('/admin/users/<int:id>/edit', methods=['GET', 'POST'])
    @login_required
    def admin_user_edit(id):
        """Edit user"""
        if not current_user.is_admin:
            return redirect(url_for('home'))
        
        user = User.query.get_or_404(id)
        
        if request.method == 'POST':
            user.username = request.form.get('username')
            user.email = request.form.get('email')
            user.is_admin = request.form.get('is_admin') == 'on'
            
            password = request.form.get('password')
            if password:
                user.set_password(password)
            
            db.session.commit()
            flash('User updated successfully!', 'success')
            return redirect(url_for('admin_users'))
        
        return render_template('admin/user_form.html', user=user)
    
    @app.route('/admin/users/<int:id>/delete', methods=['POST'])
    @login_required
    def admin_user_delete(id):
        """Delete user"""
        if not current_user.is_admin:
            return redirect(url_for('home'))
        
        user = User.query.get_or_404(id)
        db.session.delete(user)
        db.session.commit()
        flash('User deleted successfully!', 'success')
        return redirect(url_for('admin_users'))
    
    # ===== ADMIN AD ROUTES =====
    @app.route('/admin/ads')
    @login_required
    def admin_ads():
        """Admin ad management"""
        if not current_user.is_admin:
            return redirect(url_for('home'))
        
        ads = Ad.query.order_by(Ad.placement).all()
        return render_template('admin/ads.html', ads=ads)
    
    @app.route('/admin/ads/<int:id>/toggle', methods=['POST'])
    @login_required
    def admin_ad_toggle(id):
        """Toggle ad active status"""
        if not current_user.is_admin:
            return jsonify({'error': 'Unauthorized'}), 403
        
        ad = Ad.query.get_or_404(id)
        ad.is_active = not ad.is_active
        db.session.commit()
        
        return jsonify({
            'success': True,
            'is_active': ad.is_active,
            'message': f'Ad "{ad.title}" is now {"active" if ad.is_active else "inactive"}'
        })
    
    @app.route('/admin/ads/<int:id>/edit', methods=['GET', 'POST'])
    @login_required
    def admin_ad_edit(id):
        """Edit ad"""
        if not current_user.is_admin:
            return redirect(url_for('home'))
        
        ad = Ad.query.get_or_404(id)
        
        if request.method == 'POST':
            ad.title = request.form.get('title', ad.title)
            ad.banner_link = request.form.get('banner_link', '')
            ad.target_url = request.form.get('target_url', '')
            ad.ad_code = request.form.get('ad_code', '')
            ad.is_active = request.form.get('is_active') == 'on'
            
            db.session.commit()
            flash('Ad updated successfully!', 'success')
            return redirect(url_for('admin_ads'))
        
        return render_template('admin/ad_edit.html', ad=ad)
    
    @app.route('/admin/ads/new', methods=['GET', 'POST'])
    @login_required
    def admin_ad_create():
        """Create new ad"""
        if not current_user.is_admin:
            return redirect(url_for('home'))
        
        if request.method == 'POST':
            ad = Ad(
                title=request.form.get('title', 'New Ad'),
                placement=request.form.get('placement', 'header'),
                ad_type=request.form.get('ad_type', 'banner'),
                banner_link=request.form.get('banner_link', ''),
                target_url=request.form.get('target_url', ''),
                ad_code=request.form.get('ad_code', ''),
                is_active=request.form.get('is_active') == 'on'
            )
            
            db.session.add(ad)
            db.session.commit()
            flash('Ad created successfully!', 'success')
            return redirect(url_for('admin_ads'))
        
        return render_template('admin/ad_edit.html', ad=None)
    
    @app.route('/admin/ads/<int:id>/delete', methods=['POST'])
    @app.route('/admin/ads/<int:id>/delete', methods=['POST'])
    @login_required
    def admin_ad_delete(id):
        """Delete ad"""
        if not current_user.is_admin:
            return redirect(url_for('home'))
        
        ad = Ad.query.get_or_404(id)
        db.session.delete(ad)
        db.session.commit()
        flash('Ad deleted successfully!', 'success')
        return redirect(url_for('admin_ads'))
    
    # ===== ADMIN CATEGORIES & SETTINGS ROUTES =====
    @app.route('/admin/categories')
    @login_required
    def admin_categories():
        """Admin category management"""
        if not current_user.is_admin:
            return redirect(url_for('home'))
        flash('Categories management coming soon!', 'info')
        return redirect(url_for('admin_dashboard'))
        flash('Categories management coming soon!', 'info')
        return redirect(url_for('admin_dashboard'))
    
    @app.route('/admin/settings', methods=['GET', 'POST'])
    @login_required
    def admin_settings():
        """Admin settings page with LLM and Upload Host configuration"""
        if not current_user.is_admin:
            return redirect(url_for('home'))
        
        from models import Setting
        
        if request.method == 'POST':
            section = request.form.get('section', 'all')
            
            if section == 'llm':
                # LLM Configuration only
                Setting.set('llm_base_url', request.form.get('llm_base_url', ''), 'Base URL for LLM API')
                Setting.set('llm_api_key', request.form.get('llm_api_key', ''), 'API key for LLM')
                Setting.set('llm_model', request.form.get('llm_model', 'koboldcpp/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-Q8_0'), 'Model name for LLM')
                Setting.set('llm_use_local', '1' if request.form.get('llm_use_local') else '0', 'Use local LLM (no API key required)')
                Setting.set('llm_temperature', request.form.get('llm_temperature', '0.7'), 'Temperature for generation')
                Setting.set('llm_max_tokens', request.form.get('llm_max_tokens', '4096'), 'Max tokens for response')
                flash('LLM Configuration saved successfully!', 'success')
                
            elif section == 'upfiles':
                # Upload Host Configuration only
                Setting.set('upfiles_endpoint', request.form.get('upfiles_endpoint', 'https://api.upfiles.com/upload'), 'UpFiles API endpoint')
                Setting.set('upfiles_token', request.form.get('upfiles_token', ''), 'UpFiles API token')
                Setting.set('upfiles_folder_alias', request.form.get('upfiles_folder_alias', ''), 'UpFiles folder alias')
                flash('Upload Host Configuration saved successfully!', 'success')
                
            elif section == 'site':
                # Site Settings only
                Setting.set('site_name', request.form.get('site_name', 'ComicVault'), 'Site name')
                Setting.set('site_description', request.form.get('site_description', ''), 'Site description')
                Setting.set('items_per_page', request.form.get('items_per_page', '12'), 'Items per page')
                Setting.set('maintenance_mode', '1' if request.form.get('maintenance_mode') else '0', 'Maintenance mode')
                flash('Site Settings saved successfully!', 'success')
            
            return redirect(url_for('admin_settings'))
        
        # Get all settings
        settings = {}
        all_settings = Setting.query.all()
        for setting in all_settings:
            settings[setting.key] = setting.value
        
        return render_template('admin/settings.html', settings=settings)

    def admin_settings_reset():
        """Reset settings to defaults"""
        if not current_user.is_admin:
            return jsonify({'success': False, 'message': 'Unauthorized'}), 403
        
        from models import Setting
        
        # Reset to default values
        defaults = {
            'llm_base_url': '',
            'llm_api_key': '',
            'llm_model': 'koboldcpp/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-Q8_0',
            'llm_use_local': '1',
            'llm_temperature': '0.7',
            'llm_max_tokens': '4096',
            'upfiles_endpoint': 'https://api.upfiles.com/upload',
            'upfiles_token': '',
            'upfiles_folder_alias': '',
            'site_name': 'ComicVault',
            'site_description': '',
            'items_per_page': '12',
            'maintenance_mode': '0'
        }
        
        for key, value in defaults.items():
            Setting.set(key, value)
        
        return jsonify({'success': True, 'message': 'Settings reset to defaults'})
    
    @app.route('/admin/test_llm', methods=['POST'])
    @login_required
    def admin_test_llm():
        """Test LLM connection"""
        if not current_user.is_admin:
            return jsonify({'success': False, 'message': 'Unauthorized'}), 403
        
        from models import Setting
        import requests
        
        base_url = Setting.get('llm_base_url')
        api_key = Setting.get('llm_api_key')
        model = Setting.get('llm_model', 'gpt-4-vision-preview')
        
        if not base_url:
            return jsonify({'success': False, 'message': 'LLM Base URL not configured'})
        
        try:
            headers = {'Content-Type': 'application/json'}
            if api_key:
                headers['Authorization'] = f'Bearer {api_key}'
            
            # Simple test request
            response = requests.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json={
                    'model': model,
                    'messages': [{'role': 'user', 'content': 'Hello'}],
                    'max_tokens': 10
                },
                timeout=10
            )
            
            if response.status_code == 200:
                return jsonify({'success': True, 'message': 'Connection successful'})
            else:
                return jsonify({'success': False, 'message': f'API returned status {response.status_code}'})
        
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/admin/test_upfiles', methods=['POST'])
    @login_required
    def admin_test_upfiles():
        """Test UpFiles connection"""
        if not current_user.is_admin:
            return jsonify({'success': False, 'message': 'Unauthorized'}), 403
        
        from models import Setting
        import requests
        
        token = Setting.get('upfiles_token')
        endpoint = Setting.get('upfiles_endpoint', 'https://api.upfiles.com/upload')
        
        if not token:
            return jsonify({'success': False, 'message': 'UpFiles token not configured'})
        
        try:
            # Create a small test file
            import io
            test_file = io.BytesIO(b'test')
            
            files = {'file': ('test.txt', test_file, 'text/plain')}
            data = {'token': token}
            
            response = requests.post(
                endpoint,
                data=data,
                files=files,
                timeout=30
            )
            
            result = response.json()
            
            if result.get('status') == 'success':
                return jsonify({'success': True, 'message': 'Connection successful', 'url': result.get('url')})
            else:
                return jsonify({'success': False, 'message': result.get('message', 'Unknown error')})
        
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/admin/analyze_pdf', methods=['POST'])
    @login_required
    def admin_analyze_pdf():
        """Analyze PDF with Vision LLM for metadata extraction and upload to external host"""
        if not current_user.is_admin:
            return jsonify({'success': False, 'message': 'Unauthorized'}), 403
        
        if 'pdf_file' not in request.files:
            return jsonify({'success': False, 'message': 'No PDF file provided'}), 400
        
        pdf_file = request.files['pdf_file']
        if pdf_file.filename == '':
            return jsonify({'success': False, 'message': 'No file selected'}), 400
        
        try:
            import tempfile
            
            # Save PDF temporarily
            temp_dir = tempfile.mkdtemp()
            temp_pdf_path = os.path.join(temp_dir, secure_filename(pdf_file.filename))
            pdf_file.save(temp_pdf_path)
            
            # Extract metadata using Vision LLM
            from vision_llm import ComicMetadataExtractor, optimize_description_for_seo
            extractor = ComicMetadataExtractor()
            
            metadata, cover_path = extractor.extract_from_pdf_first_page(temp_pdf_path)
            
            if 'error' in metadata:
                return jsonify({'success': False, 'message': metadata['error']}), 500
            
            # Save cover image if extracted
            cover_image_url = None
            if cover_path and os.path.exists(cover_path):
                cover_filename = f"cover_{secure_filename(pdf_file.filename.rsplit('.', 1)[0])}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                cover_dest_path = os.path.join(app.config['UPLOAD_FOLDER'], 'covers', cover_filename)
                
                # Ensure covers directory exists
                os.makedirs(os.path.dirname(cover_dest_path), exist_ok=True)
                
                # Copy the extracted cover to the uploads folder
                shutil.copy(cover_path, cover_dest_path)
                
                cover_image_url = url_for('static', filename=f'covers/{cover_filename}')
            
            # Upload PDF to external host (UpFiles)
            download_url = None
            try:
                from models import Setting
                import requests
                
                token = Setting.get('upfiles_token')
                endpoint = Setting.get('upfiles_endpoint', 'https://api.upfiles.com/upload')
                
                if token and endpoint:
                    with open(temp_pdf_path, 'rb') as pdf_data:
                        files = {'file': (secure_filename(pdf_file.filename), pdf_data, 'application/pdf')}
                        data = {'token': token}
                        
                        upload_response = requests.post(
                            endpoint,
                            data=data,
                            files=files,
                            timeout=60
                        )
                        
                        upload_result = upload_response.json()
                        
                        if upload_result.get('status') == 'success':
                            download_url = upload_result.get('url')
                        else:
                            app.logger.warning(f"Upload host returned error: {upload_result.get('message', 'Unknown error')}")
                else:
                    app.logger.warning("Upload host not configured - skipping external upload")
            except Exception as upload_error:
                app.logger.error(f"Failed to upload to external host: {str(upload_error)}")
                # Don't fail the whole operation if upload fails
            
            # Optimize description for SEO
            if 'description' in metadata:
                metadata['description'] = optimize_description_for_seo(metadata['description'])
            
            # Clean up temp file
            try:
                os.remove(temp_pdf_path)
                os.rmdir(temp_dir)
            except:
                pass
            
            # Return extracted data with download URL
            return jsonify({
                'success': True,
                'title': metadata.get('title', ''),
                'episode': metadata.get('episode', ''),
                'author': metadata.get('author', ''),
                'artist': metadata.get('artist', ''),
                'description': metadata.get('description', ''),
                'category': metadata.get('category', ''),
                'tags': metadata.get('tags', []),
                'cover_image_url': cover_image_url,
                'download_url': download_url
            })
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({'success': False, 'message': f'Analysis failed: {str(e)}'}), 500
    
    # ===== API ROUTES =====
    
    @app.route('/api/ai/extract_metadata', methods=['POST'])
    @login_required
    def api_ai_extract_metadata():
        if not current_user.is_admin:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
            
        if 'image' not in request.files:
            return jsonify({'success': False, 'error': 'No image provided'}), 400
            
        file = request.files['image']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No selected file'}), 400
            
        try:
            from vision_llm import ComicMetadataExtractor, optimize_description_for_seo
            import base64
            
            # Read file data directly
            file_data = file.read()
            base64_image = base64.b64encode(file_data).decode('utf-8')
            
            extractor = ComicMetadataExtractor()
            metadata = extractor._call_vision_api(base64_image)
            
            if not metadata:
                return jsonify({'success': False, 'error': 'Failed to extract metadata'}), 500
                
            if 'description' in metadata:
                metadata['description'] = optimize_description_for_seo(metadata['description'])
                
            metadata['success'] = True
            return jsonify(metadata)
            
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/toggle_library', methods=['POST'])
    @login_required
    def toggle_library():
        """Add or remove comic from user library"""
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'success': False, 'error': 'Invalid JSON data'}), 400
        
        comic_id = data.get('comic_id')
        if not comic_id:
            return jsonify({'success': False, 'error': 'Missing comic_id'}), 400
        
        # Check if comic exists
        comic = Comic.query.get_or_404(comic_id)
        
        # Check if already in library (via reading progress)
        progress = ReadingProgress.query.filter_by(
            user_id=current_user.id, comic_id=comic_id
        ).first()
        
        if progress:
            # Remove from library by deleting progress
            db.session.delete(progress)
            db.session.commit()
            return jsonify({'success': True, 'in_library': False, 'message': 'Removed from library'})
        else:
            # Add to library by creating initial progress
            progress = ReadingProgress(
                user_id=current_user.id,
                comic_id=comic_id,
                current_page=1,
                total_pages=comic.total_pages or 0
            )
            db.session.add(progress)
            db.session.commit()
            return jsonify({'success': True, 'in_library': True, 'message': 'Added to library'})
    
    @app.route('/api/rate_comic', methods=['POST'])
    @login_required
    def api_rate_comic():
        """Rate a comic via AJAX/JSON"""
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'success': False, 'error': 'Invalid JSON data'}), 400
        
        comic_id = data.get('comic_id')
        score = data.get('score') or data.get('rating')
        
        if not score or not 1 <= int(score) <= 5:
            return jsonify({'error': 'Score must be between 1 and 5'}), 400
        
        return _process_rating(current_user.id, comic_id, int(score))
    
    @app.route('/comic/<int:id>/rate', methods=['POST'])
    @login_required
    def rate_comic(id):
        """Rate a comic via form submission"""
        score = request.form.get('rating', type=int)
        
        if not score or not 1 <= score <= 5:
            flash('Rating must be between 1 and 5 stars', 'error')
            return redirect(url_for('comic_detail', id=id))
        
        result = _process_rating(current_user.id, id, score)
        if isinstance(result, tuple):
            data, status = result
            if status != 200:
                flash(data.get('error', 'Failed to submit rating'), 'error')
            else:
                flash('Thank you for rating!', 'success')
        else:
            flash('Thank you for rating!', 'success')
        
        return redirect(url_for('comic_detail', id=id))
    
    def _process_rating(user_id, comic_id, score):
        """Process rating submission"""
        # Update or create rating
        rating = Rating.query.filter_by(
            user_id=user_id, comic_id=comic_id
        ).first()
        
        if rating:
            rating.score = score
        else:
            rating = Rating(user_id=user_id, comic_id=comic_id, score=score)
            db.session.add(rating)
        
        db.session.commit()
        
        # Update comic's average rating
        comic = Comic.query.get(comic_id)
        if comic:
            comic.update_rating()
        
        avg_rating = comic.average_rating if comic else 0
        total_ratings = comic.ratings.count() if comic else 0
        
        return jsonify({
            'success': True, 
            'new_rating': avg_rating,
            'new_average': round(avg_rating, 1),
            'total_ratings': total_ratings
        })
    
    # ===== BOOKMARK API ROUTES =====
    @app.route('/api/bookmarks', methods=['GET'])
    @login_required
    def get_bookmarks():
        """Get all bookmarks for the current user"""
        bookmarks = Bookmark.query.filter_by(user_id=current_user.id).order_by(Bookmark.created_at.desc()).all()
        return jsonify({'success': True, 'bookmarks': [b.to_dict() for b in bookmarks]})
    
    @app.route('/api/bookmarks/comic/<int:comic_id>', methods=['GET'])
    @login_required
    def get_comic_bookmarks(comic_id):
        """Get bookmarks for a specific comic"""
        bookmarks = Bookmark.query.filter_by(user_id=current_user.id, comic_id=comic_id).order_by(Bookmark.page_number).all()
        return jsonify({'success': True, 'bookmarks': [b.to_dict() for b in bookmarks]})
    
    @app.route('/api/bookmarks', methods=['POST'])
    @login_required
    def add_bookmark():
        """Add a new bookmark"""
        data = request.get_json()
        comic_id = data.get('comic_id')
        chapter_id = data.get('chapter_id')
        page_number = data.get('page_number', 1)
        note = data.get('note', '')
        
        if not comic_id:
            return jsonify({'success': False, 'message': 'Comic ID is required'}), 400
        
        existing = Bookmark.query.filter_by(user_id=current_user.id, comic_id=comic_id, chapter_id=chapter_id, page_number=page_number).first()
        if existing:
            return jsonify({'success': False, 'message': 'Bookmark already exists'}), 409
        
        bookmark = Bookmark(user_id=current_user.id, comic_id=comic_id, chapter_id=chapter_id, page_number=page_number, note=note)
        db.session.add(bookmark)
        db.session.commit()
        return jsonify({'success': True, 'bookmark': bookmark.to_dict()}), 201
    
    @app.route('/api/bookmarks/<int:bookmark_id>', methods=['DELETE'])
    @login_required
    def delete_bookmark(bookmark_id):
        """Delete a bookmark"""
        bookmark = Bookmark.query.filter_by(id=bookmark_id, user_id=current_user.id).first()
        if not bookmark:
            return jsonify({'success': False, 'message': 'Bookmark not found'}), 404
        db.session.delete(bookmark)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Bookmark deleted'})
    
    @app.route('/api/bookmarks/<int:bookmark_id>', methods=['PUT'])
    @login_required
    def update_bookmark(bookmark_id):
        """Update a bookmark's note"""
        bookmark = Bookmark.query.filter_by(id=bookmark_id, user_id=current_user.id).first()
        if not bookmark:
            return jsonify({'success': False, 'message': 'Bookmark not found'}), 404
        data = request.get_json()
        if 'note' in data:
            bookmark.note = data['note']
        db.session.commit()
        return jsonify({'success': True, 'bookmark': bookmark.to_dict()})
    
    # ===== READING PROGRESS API ROUTES =====
    @app.route('/api/reading-progress', methods=['GET'])
    @login_required
    def get_reading_progress():
        """Get all reading progress for the current user"""
        progress_list = ReadingProgress.query.filter_by(user_id=current_user.id).order_by(ReadingProgress.last_read_at.desc()).all()
        return jsonify({'success': True, 'progress': [p.to_dict() for p in progress_list]})
    
    @app.route('/api/reading-progress/comic/<int:comic_id>', methods=['GET'])
    @login_required
    def get_comic_reading_progress(comic_id):
        """Get reading progress for a specific comic"""
        progress_list = ReadingProgress.query.filter_by(user_id=current_user.id, comic_id=comic_id).order_by(ReadingProgress.chapter_id).all()
        return jsonify({'success': True, 'progress': [p.to_dict() for p in progress_list]})
    
    @app.route('/api/reading-progress', methods=['POST'])
    @login_required
    def update_reading_progress():
        """Update or create reading progress"""
        data = request.get_json()
        comic_id = data.get('comic_id')
        chapter_id = data.get('chapter_id')
        page_number = data.get('page_number', 1)
        total_pages = data.get('total_pages', 1)
        time_spent = data.get('time_spent', 0)
        
        if not comic_id:
            return jsonify({'success': False, 'message': 'Comic ID is required'}), 400
        
        progress = ReadingProgress.query.filter_by(user_id=current_user.id, comic_id=comic_id, chapter_id=chapter_id).first()
        
        if progress:
            progress.update_progress(page_number, total_pages, time_spent)
        else:
            progress = ReadingProgress(user_id=current_user.id, comic_id=comic_id, chapter_id=chapter_id, page_number=page_number, total_pages=total_pages)
            progress.update_progress(page_number, total_pages, time_spent)
            db.session.add(progress)
        
        db.session.commit()
        return jsonify({'success': True, 'progress': progress.to_dict()})
    
    @app.route('/api/reading-progress/completed', methods=['GET'])
    @login_required
    def get_completed_reading():
        """Get all completed comics for the current user"""
        completed = ReadingProgress.query.filter_by(user_id=current_user.id, completed=True).order_by(ReadingProgress.completed_at.desc()).all()
        return jsonify({'success': True, 'completed': [p.to_dict() for p in completed]})
    
    @app.route('/api/reading-progress/continue-reading', methods=['GET'])
    @login_required
    def get_continue_reading():
        """Get comics to continue reading"""
        in_progress = ReadingProgress.query.filter(ReadingProgress.user_id == current_user.id, ReadingProgress.completed == False).order_by(ReadingProgress.last_read_at.desc()).limit(10).all()
        return jsonify({'success': True, 'continue_reading': [p.to_dict() for p in in_progress]})
    
    # ===== CHAPTER NAVIGATION API ROUTES =====
    @app.route('/api/comics/<int:comic_id>/chapters', methods=['GET'])
    @login_required
    def get_comic_chapters(comic_id):
        """Get all chapters for a comic"""
        chapters = Chapter.query.filter_by(comic_id=comic_id).order_by(Chapter.number).all()
        return jsonify({'success': True, 'chapters': [{'id': c.id, 'number': c.number, 'title': c.title, 'page_count': c.page_count or 0} for c in chapters]})
    
    @app.route('/api/chapters/<int:chapter_id>/next', methods=['GET'])
    @login_required
    def get_next_chapter(chapter_id):
        """Get the next chapter"""
        chapter = Chapter.query.get(chapter_id)
        if not chapter:
            return jsonify({'success': False, 'message': 'Chapter not found'}), 404
        next_chapter = Chapter.query.filter(Chapter.comic_id == chapter.comic_id, Chapter.number > chapter.number).order_by(Chapter.number).first()
        if next_chapter:
            return jsonify({'success': True, 'chapter': {'id': next_chapter.id, 'number': next_chapter.number, 'title': next_chapter.title}})
        return jsonify({'success': True, 'chapter': None, 'message': 'No next chapter'})
    
    @app.route('/api/chapters/<int:chapter_id>/prev', methods=['GET'])
    @login_required
    def get_prev_chapter(chapter_id):
        """Get the previous chapter"""
        chapter = Chapter.query.get(chapter_id)
        if not chapter:
            return jsonify({'success': False, 'message': 'Chapter not found'}), 404
        prev_chapter = Chapter.query.filter(Chapter.comic_id == chapter.comic_id, Chapter.number < chapter.number).order_by(Chapter.number.desc()).first()
        if prev_chapter:
            return jsonify({'success': True, 'chapter': {'id': prev_chapter.id, 'number': prev_chapter.number, 'title': prev_chapter.title}})
        return jsonify({'success': True, 'chapter': None, 'message': 'No previous chapter'})
    
    # Phase 2: Missing Search & Discovery Endpoints
    
    @app.route('/api/comics/random', methods=['GET'])
    def get_random_comic():
        """Get a random comic from the database"""
        comic = Comic.query.order_by(db.func.random()).first()
        if comic:
            return jsonify({
                'success': True,
                'comic': {
                    'id': comic.id,
                    'title': comic.title,
                    'slug': comic.slug,
                    'cover_image': comic.cover_image,
                    'author': comic.author,
                    'rating': float(comic.rating) if comic.rating else 0
                }
            })
        return jsonify({'success': False, 'message': 'No comics found'}), 404
    
    @app.route('/api/comics/<int:comic_id>/similar', methods=['GET'])
    def get_similar_comics(comic_id):
        """Get similar comics based on tags and category"""
        comic = Comic.query.get_or_404(comic_id)
        
        # Get comic's tags
        comic_tags = [tag.name for tag in comic.tags]
        
        # Find comics with similar tags, excluding current comic
        similar = Comic.query.filter(
            Comic.id != comic_id,
            Comic.status == 'ongoing'
        ).join(Comic.tags).filter(
            ComicTag.name.in_(comic_tags)
        ).distinct().limit(6).all()
        
        # If not enough, fill with random comics
        if len(similar) < 6:
            additional = Comic.query.filter(
                Comic.id != comic_id,
                Comic.id.notin_([c.id for c in similar])
            ).order_by(db.func.random()).limit(6 - len(similar)).all()
            similar.extend(additional)
        
        return jsonify({
            'success': True,
            'comics': [{
                'id': c.id,
                'title': c.title,
                'slug': c.slug,
                'cover_image': c.cover_image,
                'author': c.author,
                'rating': float(c.rating) if c.rating else 0,
                'tags': [t.name for t in c.tags]
            } for c in similar]
        })
    
    @app.route('/api/tags/autocomplete', methods=['GET'])
    def tags_autocomplete():
        """Get tag suggestions for autocomplete"""
        query = request.args.get('q', '').strip()
        if len(query) < 2:
            return jsonify({'success': True, 'tags': []})
        
        tags = ComicTag.query.filter(
            ComicTag.name.ilike(f'{query}%')
        ).order_by(ComicTag.name).limit(10).all()
        
        return jsonify({
            'success': True,
            'tags': [tag.name for tag in tags]
        })
    
    @app.route('/discover')
    def discover():
        """Discovery page with search, trending, and recommendations"""
        # Get trending comics
        trending = Comic.query.order_by(Comic.views.desc()).limit(12).all()
        # Get new releases
        new_releases = Comic.query.order_by(Comic.created_at.desc()).limit(12).all()
        # Get top rated
        top_rated = Comic.query.filter(Comic.rating >= 4.0).order_by(Comic.rating.desc()).limit(12).all()
        # Get all tags for filtering
        all_tags = ComicTag.query.order_by(ComicTag.name).all()
        
        return render_template('user/discover.html',
                             trending=trending,
                             new_releases=new_releases,
                             top_rated=top_rated,
                             all_tags=all_tags)
    
    # Error handlers
    @app.errorhandler(404)
    def not_found(error):
        return render_template('errors/404.html'), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template('errors/500.html'), 500
    
    return app

# Create app instance
app = create_app()

if __name__ == '__main__':
    with app.app_context():
        init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
