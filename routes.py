"""
ComicVault - Flask Application Routes
Main application routes and API endpoints
"""

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, send_from_directory, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from models import db, User, Comic, Category, Tag, ComicTag, ReadingProgress, Rating, UserLibrary, Setting, Ad, Chapter, Comment, CommentLike, ReadingList, ReadingListItem, Activity, Follow, ComicPage
from datetime import datetime
import os
import uuid
import shutil
import bleach
from extensions import limiter

# Import unified uploader & cloud storage service
from unified_uploader import UnifiedUploader, create_uploader_from_config
from catbox_service import CatboxService

# Helper to preserve cloud URLs vs local basenames
def format_storage_ref(val):
    if not val:
        return None
    val_str = str(val).strip()
    if val_str.startswith(('http://', 'https://')):
        return val_str
    return os.path.basename(val_str)

# Create Blueprint
main = Blueprint('main', __name__)

# Helper functions
def allowed_file(filename):
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

# ============================
# Authentication Routes
# ============================

@main.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login():
    """User login page and handler"""
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))
    
    if request.method == 'POST':
        # Support both 'username' (from app.py) and 'email' (from routes.py)
        identifier = request.form.get('email') or request.form.get('username')
        password = request.form.get('password')
        remember = request.form.get('remember', False) == 'on'
        
        # Search by email or username
        user = User.query.filter((User.email == identifier) | (User.username == identifier)).first()
        
        if user and user.check_password(password):
            login_user(user, remember=remember)
            flash(f'Welcome back, {user.username}!', 'success')
            
            next_page = request.args.get('next')
            if next_page and next_page.startswith('/'):
                return redirect(next_page)
            
            # Redirect admin users to dashboard by default if no next page
            if user.is_admin:
                return redirect(url_for('main.admin_dashboard'))
                
            return redirect(url_for('main.home'))
        else:
            flash('Invalid email/username or password', 'danger')
    
    return render_template('auth/login.html')


@main.route('/register', methods=['GET', 'POST'])
@limiter.limit("10 per hour")
def register():
    """User registration page and handler"""
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))
    
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        email = (request.form.get('email') or '').strip()
        password = request.form.get('password') or ''
        confirm_password = request.form.get('confirm_password') or ''
        security_answer = request.form.get('security_answer') or ''
        
        # Validation using strict regex & fixed length helpers
        from security_utils import (
            validate_username,
            validate_email,
            validate_password,
            validate_security_answer
        )
        
        valid_u, msg_u = validate_username(username)
        if not valid_u:
            flash(msg_u, 'danger')
            return render_template('auth/register.html')
            
        valid_e, msg_e = validate_email(email)
        if not valid_e:
            flash(msg_e, 'danger')
            return render_template('auth/register.html')
            
        valid_p, msg_p = validate_password(password)
        if not valid_p:
            flash(msg_p, 'danger')
            return render_template('auth/register.html')
            
        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('auth/register.html')
            
        valid_s, msg_s = validate_security_answer(security_answer)
        if not valid_s:
            flash(msg_s, 'danger')
            return render_template('auth/register.html')
            
        # 18+ Confirmation Check
        if not request.form.get('age_confirm'):
            flash('You must confirm that you are 18+ to create an account.', 'danger')
            return render_template('auth/register.html')
        
        if User.query.filter(db.func.lower(User.username) == username.lower()).first():
            flash('Username is already taken.', 'danger')
            return render_template('auth/register.html')
        
        if User.query.filter(db.func.lower(User.email) == email.lower()).first():
            flash('Email is already registered.', 'danger')
            return render_template('auth/register.html')
        
        # Create user
        user = User(username=username, email=email)
        user.set_password(password)
        user.set_security_answer(security_answer)
        db.session.add(user)
        db.session.commit()
        
        flash('Account created successfully! Please log in.', 'success')
        return redirect(url_for('main.login'))
    
    return render_template('auth/register.html')


@main.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def forgot_password():
    """Step 1 of password recovery: Verify email and childhood favourite TV show"""
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))
        
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip()
        security_answer = request.form.get('security_answer') or ''
        
        from security_utils import validate_email, validate_security_answer
        valid_e, msg_e = validate_email(email)
        if not valid_e:
            flash(msg_e, 'danger')
            return render_template('auth/forgot_password.html')
            
        valid_s, msg_s = validate_security_answer(security_answer)
        if not valid_s:
            flash(msg_s, 'danger')
            return render_template('auth/forgot_password.html')
            
        user = User.query.filter(db.func.lower(User.email) == email.lower()).first()
        if user and user.check_security_answer(security_answer):
            from itsdangerous import URLSafeTimedSerializer
            import hashlib
            serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
            pw_sig = hashlib.sha256((user.password_hash or '').encode()).hexdigest()[:16]
            token = serializer.dumps({'user_id': user.id, 'pw_sig': pw_sig}, salt='pw-reset-salt')
            return redirect(url_for('main.reset_password', token=token))
        else:
            flash('Invalid email or security answer. Please check your details and try again.', 'danger')
            return render_template('auth/forgot_password.html')
            
    return render_template('auth/forgot_password.html')


@main.route('/reset-password', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def reset_password():
    """Step 2 of password recovery: Set new password with valid token"""
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))
        
    token = request.args.get('token') or request.form.get('token')
    if not token:
        flash('Missing password reset token. Please request a new link.', 'danger')
        return redirect(url_for('main.forgot_password'))
        
    from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    
    try:
        data = serializer.loads(token, salt='pw-reset-salt', max_age=900)  # 15 minutes expiry
        user_id = data.get('user_id')
        user = User.query.get(user_id)
        import hashlib
        current_sig = hashlib.sha256((user.password_hash or '').encode()).hexdigest()[:16] if user else ''
        if not user or current_sig != data.get('pw_sig'):
            flash('This password reset link has expired or has already been used.', 'warning')
            return redirect(url_for('main.forgot_password'))
    except (SignatureExpired, BadSignature, Exception):
        flash('This password reset link is invalid or has expired. Please request a new link.', 'danger')
        return redirect(url_for('main.forgot_password'))
        
    if request.method == 'POST':
        password = request.form.get('password') or ''
        confirm_password = request.form.get('confirm_password') or ''
        
        from security_utils import validate_password
        valid_p, msg_p = validate_password(password)
        if not valid_p:
            flash(msg_p, 'danger')
            return render_template('auth/reset_password.html', token=token)
            
        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('auth/reset_password.html', token=token)
            
        user.set_password(password)
        db.session.commit()
        
        flash('Password reset successful! Please log in with your new password.', 'success')
        return redirect(url_for('main.login'))
        
    return render_template('auth/reset_password.html', token=token)


@main.route('/logout')
@login_required
def logout():
    """User logout"""
    logout_user()
    flash('You have been logged out', 'info')
    return redirect(url_for('main.login'))


# ============================
# Discovery & General Routes
# ============================

@main.route('/discover')
def discover():
    """Discover page with advanced search and filtering"""
    # Get filter parameters
    query = request.args.get('q', '')
    category = request.args.get('category', '')
    sort = request.args.get('sort', 'recent')
    page = request.args.get('page', 1, type=int)
    per_page = 24
    
    # Base query
    comics_query = Comic.query.filter(Comic.visibility == 'public')
    
    # Apply text search
    if query:
        comics_query = comics_query.filter(
            db.or_(
                Comic.title.ilike(f'%{query}%'),
                Comic.author.ilike(f'%{query}%'),
                Comic.artist.ilike(f'%{query}%')
            )
        )
    
    # Apply category filter
    if category:
        comics_query = comics_query.filter(Comic.category == category)
    
    # Apply sorting
    if sort == 'title':
        comics_query = comics_query.order_by(Comic.title.asc())
    elif sort == 'rating':
        comics_query = comics_query.order_by(Comic.average_rating.desc())
    elif sort == 'popular':
        comics_query = comics_query.order_by(Comic.view_count.desc())
    else:
        comics_query = comics_query.order_by(Comic.created_at.desc())
    
    pagination = comics_query.paginate(page=page, per_page=per_page, error_out=False)
    
    # Get categories for filter dropdown
    categories = Category.query.all()
    
    return render_template('user/discover.html',
                          comics=pagination.items,
                          pagination=pagination,
                          query=query,
                          selected_category=category,
                          sort=sort,
                          categories=categories)


@main.route('/api/tags/autocomplete')
def tags_autocomplete():
    """Autocomplete API for tags"""
    query = request.args.get('q', '')
    if len(query) < 2:
        return jsonify({'tags': []})
    
    # Search matching tags
    tags = Tag.query.filter(Tag.name.ilike(f'%{query}%')).limit(10).all()
    
    return jsonify({
        'tags': [{'id': t.id, 'name': t.name} for t in tags]
    })


@main.route('/api/comics/random')
def random_comic():
    """Get a random comic"""
    count = Comic.query.filter(Comic.visibility == 'public').count()
    if count == 0:
        return jsonify({'success': False, 'message': 'No comics available'}), 404
    
    import random
    offset = random.randint(0, count - 1)
    comic = Comic.query.filter(Comic.visibility == 'public').offset(offset).first()
    
    if not comic:
        return jsonify({'success': False, 'message': 'No comics found'}), 404
    
    return jsonify({
        'success': True,
        'comic': {
            'id': comic.id,
            'title': comic.title,
            'slug': comic.slug,
            'cover_image': comic.cover_image,
            'url': url_for('main.comic_detail', comic_id=comic.id)
        }
    })


@main.route('/api/comics/<int:comic_id>/similar')
def similar_comics(comic_id):
    """Get similar comics based on category and tags"""
    comic = Comic.query.get_or_404(comic_id)
    
    # Get comics in the same category
    similar = Comic.query.filter(
        Comic.id != comic_id,
        Comic.visibility == 'public',
        Comic.category == comic.category
    ).order_by(Comic.average_rating.desc()).limit(6).all()
    
    # If not enough in same category, add by shared tags
    if len(similar) < 6:
        comic_tags = [t.id for t in comic.tags]
        if comic_tags:
            additional = Comic.query.filter(
                Comic.id != comic_id,
                Comic.visibility == 'public',
                Comic.id.notin_([c.id for c in similar])
            ).join(ComicTag).filter(
                ComicTag.tag_id.in_(comic_tags)
            ).order_by(Comic.average_rating.desc()).limit(6 - len(similar)).all()
            similar.extend(additional)
    
    return jsonify({
        'success': True,
        'comics': [{
            'id': c.id,
            'title': c.title,
            'slug': c.slug,
            'cover_image': c.cover_image,
            'author': c.author,
            'average_rating': c.average_rating,
            'url': url_for('main.comic_detail', comic_id=c.id)
        } for c in similar]
    })


@main.route('/')
def home():
    """Home page with featured comics and categories"""
    # Get featured comics (highest rated or manually featured)
    featured = Comic.query.filter(
        (Comic.visibility == 'public') & ((Comic.is_featured == True) | (Comic.average_rating >= 4.0))
    ).order_by(Comic.average_rating.desc()).limit(12).all()
    
    # Get recently added
    recent = Comic.query.filter_by(visibility='public').order_by(
        Comic.created_at.desc()
    ).limit(12).all()
    
    # Get trending (most views)
    trending = Comic.query.filter_by(visibility='public').order_by(
        Comic.view_count.desc()
    ).limit(12).all()
    
    # Get categories
    categories = Category.query.all()
    
    # Get continue reading for logged-in users
    continue_reading = []
    if current_user.is_authenticated:
        latest_progress = ReadingProgress.query.filter_by(
            user_id=current_user.id
        ).order_by(ReadingProgress.last_read_at.desc()).first()
        
        if latest_progress and latest_progress.percentage < 100:
            comic = Comic.query.get(latest_progress.comic_id)
            if comic:
                continue_reading.append({
                    'comic': comic,
                    'current_page': latest_progress.current_page,
                    'total_pages': latest_progress.total_pages,
                    'percentage': latest_progress.percentage,
                    'resume_url': url_for('main.read_comic', comic_id=comic.id)
                })
    
    return render_template('home.html', 
                         featured=featured, 
                         recent=recent,
                         trending=trending,
                         categories=categories,
                         continue_reading=continue_reading)


@main.route('/categories')
def categories():
    """Browse all categories"""
    categories = Category.query.all()
    return render_template('categories.html', categories=categories)


@main.route('/category/<slug>')
def category_view(slug):
    """View comics in a specific category"""
    category = Category.query.filter_by(slug=slug).first_or_404()
    
    page = request.args.get('page', 1, type=int)
    per_page = 12
    
    comics_query = Comic.query.filter(
        Comic.category == category.name, 
        Comic.visibility == 'public'
    )
    
    # Sort options
    sort = request.args.get('sort', 'recent')
    if sort == 'title':
        comics_query = comics_query.order_by(Comic.title.asc())
    elif sort == 'rating':
        comics_query = comics_query.order_by(Comic.average_rating.desc())
    elif sort == 'popular':
        comics_query = comics_query.order_by(Comic.view_count.desc())
    else:
        comics_query = comics_query.order_by(Comic.created_at.desc())
    
    pagination = comics_query.paginate(page=page, per_page=per_page, error_out=False)
    
    return render_template('category.html', 
                         category=category,
                         comics=pagination,
                         page=page,
                         sort=sort)
@main.route('/trending')
def trending():
    """Trending comics page"""
    page = request.args.get('page', 1, type=int)
    per_page = 12
    
    comics_query = Comic.query.filter_by(visibility='public').order_by(Comic.view_count.desc())
    pagination = comics_query.paginate(page=page, per_page=per_page, error_out=False)
    
    return render_template('trending.html', comics=pagination.items, pagination=pagination)


@main.route('/search')
def search():
    """Advanced search comics with filters"""
    query = request.args.get('q', '').strip()
    author = request.args.get('author', '').strip()
    artist = request.args.get('artist', '').strip()
    category = request.args.get('category', '').strip()
    tags = request.args.get('tags', '').strip()
    min_rating = request.args.get('min_rating', type=float)
    max_rating = request.args.get('max_rating', type=float)
    sort = request.args.get('sort', 'relevance')  # relevance, rating, views, newest, alphabetical
    page = request.args.get('page', 1, type=int)
    per_page = 12
    
    # Base query
    comics_query = Comic.query.filter_by(visibility='public')
    
    # Apply text search
    if query:
        comics_query = comics_query.filter(
            (Comic.title.ilike(f'%{query}%')) | 
            (Comic.description.ilike(f'%{query}%'))
        )
    
    # Apply author filter
    if author:
        comics_query = comics_query.filter(Comic.author.ilike(f'%{author}%'))
    
    # Apply artist filter
    if artist:
        comics_query = comics_query.filter(Comic.artist.ilike(f'%{artist}%'))
    
    # Apply category filter
    if category:
        comics_query = comics_query.filter(Comic.category.ilike(f'%{category}%'))
    
    # Apply rating filters
    if min_rating is not None:
        comics_query = comics_query.filter(Comic.average_rating >= min_rating)
    if max_rating is not None:
        comics_query = comics_query.filter(Comic.average_rating <= max_rating)
    
    # Apply tag filtering
    tag_list = [t.strip() for t in tags.split(',') if t.strip()] if tags else []
    if tag_list:
        # Find comics that have ALL specified tags
        for tag in tag_list:
            comics_query = comics_query.filter(
                Comic.tags.any(ComicTag.tag.ilike(f'%{tag}%'))
            )
    
    # Apply sorting
    if sort == 'rating':
        comics_query = comics_query.order_by(Comic.average_rating.desc())
    elif sort == 'views':
        comics_query = comics_query.order_by(Comic.view_count.desc())
    elif sort == 'newest':
        comics_query = comics_query.order_by(Comic.created_at.desc())
    elif sort == 'alphabetical':
        comics_query = comics_query.order_by(Comic.title.asc())
    elif sort == 'updated':
        comics_query = comics_query.order_by(Comic.updated_at.desc())
    else:  # relevance - default
        # For relevance, prioritize title matches, then description
        if query:
            comics_query = comics_query.order_by(
                db.case(
                    (Comic.title.ilike(f'%{query}%'), 2),
                    (Comic.description.ilike(f'%{query}%'), 1),
                    else_=0
                ).desc(),
                Comic.view_count.desc()
            )
        else:
            comics_query = comics_query.order_by(Comic.view_count.desc())
    
    # Execute paginated query
    comics = comics_query.paginate(page=page, per_page=per_page, error_out=False)
    
    # Get all categories for filter dropdown
    categories = Category.query.all()
    
    # Get popular tags for suggestions
    popular_tags = db.session.query(ComicTag.tag, db.func.count(ComicTag.id).label('count'))\
        .group_by(ComicTag.tag)\
        .order_by(db.desc('count'))\
        .limit(20).all()
    
    return render_template('user/search_results.html', 
                          query=query,
                          author=author,
                          artist=artist,
                          category_filter=category,
                          tags=tags,
                          tag_list=tag_list,
                          min_rating=min_rating,
                          max_rating=max_rating,
                          sort=sort,
                          comics=comics,
                          categories=categories,
                          popular_tags=[t[0] for t in popular_tags])


# ============================
# Comic Viewing Routes
# ============================

@main.route('/comic/<int:comic_id>')
def comic_detail(comic_id):
    """View comic details"""
    comic = Comic.query.get_or_404(comic_id)
    
    # Increment view count
    comic.view_count += 1
    db.session.commit()
    
    # Get user's rating, library status, and reading progress if logged in
    user_rating = None
    in_library = False
    user_progress = None
    if current_user.is_authenticated:
        user_rating = Rating.query.filter_by(user_id=current_user.id, comic_id=comic_id).first()
        in_library = UserLibrary.query.filter_by(user_id=current_user.id, comic_id=comic_id).first() is not None
        user_progress = ReadingProgress.query.filter_by(user_id=current_user.id, comic_id=comic_id).first()
    
    # Get related comics (same category)
    related = Comic.query.filter(
        Comic.category == comic.category, 
        Comic.id != comic.id,
        Comic.visibility == 'public'
    ).limit(6).all()
    
    return render_template('comic/detail.html', comic=comic, user_rating=user_rating, in_library=in_library, related=related, user_progress=user_progress)


@main.route('/read/<int:comic_id>')
def read_comic(comic_id):
    """Read comic online"""
    comic = Comic.query.get_or_404(comic_id)
    
    if not comic.pdf_file:
        flash('This comic is not available for online reading.', 'warning')
        return redirect(url_for('main.comic_detail', comic_id=comic_id))
    
    # Update reading progress if logged in
    progress = None
    if current_user.is_authenticated:
        progress = ReadingProgress.query.filter_by(user_id=current_user.id, comic_id=comic_id).first()
        if not progress:
            progress = ReadingProgress(user_id=current_user.id, comic_id=comic_id, current_page=1)
            db.session.add(progress)
            db.session.commit()

    # Get more comics by same author
    author_comics = Comic.query.filter(Comic.author == comic.author, Comic.id != comic.id).limit(7).all()
    
    # Get popular tags and categories
    popular_tags_query = db.session.query(ComicTag.tag, db.func.count(ComicTag.comic_id).label('count'))\
        .group_by(ComicTag.tag)\
        .order_by(db.desc('count'))\
        .limit(10).all()
    popular_tags = [{'name': t[0]} for t in popular_tags_query]
    
    categories = Category.query.all()
    
    return render_template('comic/reader.html', 
                         comic=comic, 
                         progress=progress,
                         author_comics=author_comics,
                         popular_tags=popular_tags,
                         categories=categories)


@main.route('/api/comic/<int:comic_id>/pages')
@limiter.limit("60 per minute")
def api_comic_pages(comic_id):
    """API endpoint to get comic pages (extracted images)"""
    comic = Comic.query.get_or_404(comic_id)
    
    if not comic.pdf_file:
        return jsonify({'success': False, 'message': 'No file available'}), 404
    
    # 1. Check if ComicPage records exist in database
    db_pages = ComicPage.query.filter_by(comic_id=comic.id).order_by(ComicPage.page_number.asc()).all()
    if db_pages:
        return jsonify({
            'success': True,
            'comic_id': comic.id,
            'type': 'images',
            'pages': [{'url': p.image_url} for p in db_pages],
            'total': len(db_pages)
        })

    # 2. Check if images are already extracted locally on disk
    pages_dir = os.path.join(current_app.static_folder, 'uploads', 'pages', str(comic.id))
    image_files = []
    if os.path.exists(pages_dir):
        image_files = sorted([f for f in os.listdir(pages_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))])
    
    if image_files:
        pages = [{'url': f'/static/uploads/pages/{comic.id}/{f}'} for f in image_files]
        return jsonify({
            'success': True,
            'comic_id': comic.id,
            'type': 'images',
            'pages': pages,
            'total': len(pages)
        })

    # 3. Extract pages on demand
    cloud_enabled = Setting.get('cloud_storage_enabled') == '1'
    userhash = Setting.get('catbox_userhash', '')
    
    config_dict = {
        'UPLOAD_FOLDER': os.path.join(current_app.static_folder, 'uploads', 'comics'),
        'COVERS_FOLDER': os.path.join(current_app.static_folder, 'uploads', 'covers'),
        'CLOUD_STORAGE_ENABLED': cloud_enabled,
        'CATBOX_USERHASH': userhash
    }
    uploader = create_uploader_from_config(config_dict)
    
    # comic.pdf_file can be a local filename or an absolute cloud URL
    if comic.pdf_file.startswith(('http://', 'https://')):
        from security_utils import is_safe_url
        if not is_safe_url(comic.pdf_file):
            return jsonify({'success': False, 'message': 'Invalid comic file URL'}), 400
        source_pdf = comic.pdf_file
    else:
        from security_utils import safe_join_path
        comics_dir = os.path.join(current_app.static_folder, 'uploads', 'comics')
        source_pdf = safe_join_path(comics_dir, comic.pdf_file)
        if not source_pdf or not os.path.exists(source_pdf):
            return jsonify({'success': False, 'message': 'Comic file not found on server'}), 404

    urls = uploader.extract_pages(
        pdf_input=source_pdf,
        comic_id=str(comic.id),
        upload_to_catbox=cloud_enabled,
        catbox_userhash=userhash
    )

    if cloud_enabled and urls:
        # Save to ComicPage database table for instant future retrieval
        for idx, u in enumerate(urls):
            db.session.add(ComicPage(comic_id=comic.id, page_number=idx + 1, image_url=u))
        db.session.commit()

    pages = [{'url': url} for url in urls]
    return jsonify({
        'success': True,
        'comic_id': comic.id,
        'type': 'images',
        'pages': pages,
        'total': len(pages)
    })


# ============================
# User Library & Profile
# ============================

@main.route('/profile')
@login_required
def profile():
    """User profile page"""
    library_count = UserLibrary.query.filter_by(user_id=current_user.id).count()
    reading_progress = ReadingProgress.query.filter_by(user_id=current_user.id).all()
    ratings = Rating.query.filter_by(user_id=current_user.id).all()
    
    stats = {
        'library_count': library_count,
        'books_read': len([p for p in reading_progress if p.current_page >= p.total_pages > 0]),
        'in_progress': len([p for p in reading_progress if p.current_page < p.total_pages or p.total_pages == 0]),
        'reviews': len(ratings)
    }
    
    recent_comics = db.session.query(Comic).join(UserLibrary).filter(
        UserLibrary.user_id == current_user.id
    ).order_by(UserLibrary.added_at.desc()).limit(5).all()
    
    return render_template('user/profile.html', stats=stats, recent_comics=recent_comics)


@main.route('/library')
@login_required
def library():
    """User's saved comics library"""
    page = request.args.get('page', 1, type=int)
    
    pagination = db.session.query(Comic).join(UserLibrary).filter(
        UserLibrary.user_id == current_user.id
    ).order_by(UserLibrary.added_at.desc()).paginate(page=page, per_page=12, error_out=False)
    
    # Calculate dynamic stats
    total_comics = UserLibrary.query.filter_by(user_id=current_user.id).count()
    currently_reading = ReadingProgress.query.filter_by(user_id=current_user.id, completed=False).count()
    completed = ReadingProgress.query.filter_by(user_id=current_user.id, completed=True).count()
    
    # Sum up total time spent reading (stored in seconds)
    total_seconds = db.session.query(db.func.sum(ReadingProgress.total_time_spent)).filter_by(user_id=current_user.id).scalar() or 0
    total_hours = round(total_seconds / 3600, 1)
    
    stats = {
        'total_comics': total_comics,
        'currently_reading': currently_reading,
        'completed': completed,
        'total_hours': total_hours
    }
    
    return render_template('user/library.html', comics=pagination.items, pagination=pagination, stats=stats)


@main.route('/library/toggle/<int:comic_id>', methods=['POST'])
@main.route('/api/toggle_library', methods=['POST'])
@login_required
def toggle_library(comic_id=None):
    """Add or remove comic from user library"""
    if comic_id is None:
        data = request.get_json(silent=True)
        if data:
            comic_id = data.get('comic_id')
    
    if not comic_id:
        return jsonify({'success': False, 'error': 'Missing comic_id'}), 400
        
    library_item = UserLibrary.query.filter_by(user_id=current_user.id, comic_id=comic_id).first()
    
    if library_item:
        db.session.delete(library_item)
        action = 'removed'
        in_library = False
    else:
        library_item = UserLibrary(user_id=current_user.id, comic_id=comic_id)
        db.session.add(library_item)
        action = 'added'
        in_library = True
    
    db.session.commit()
    
    if request.is_json or request.path.startswith('/api/'):
        return jsonify({
            'success': True, 
            'action': action, 
            'in_library': in_library,
            'message': f'Comic {action} library'
        })
    
    return jsonify({'success': True, 'action': action})


@main.route('/api/reading_progress', methods=['POST'])
@login_required
def update_reading_progress():
    """Update reading progress via AJAX"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'success': False, 'error': 'Invalid JSON data'}), 400
    
    comic_id = data.get('comic_id')
    current_page = data.get('current_page')
    total_pages = data.get('total_pages')
    
    if not comic_id or current_page is None:
        return jsonify({'success': False, 'error': 'Missing required fields'}), 400
    
    progress = ReadingProgress.query.filter_by(
        user_id=current_user.id, comic_id=comic_id
    ).first()
    
    if progress:
        progress.current_page = current_page
        if total_pages:
            progress.total_pages = total_pages
        progress.last_read = datetime.utcnow()
        progress.update_percentage()  # Calculate percentage
    else:
        progress = ReadingProgress(
            user_id=current_user.id,
            comic_id=comic_id,
            current_page=current_page,
            total_pages=total_pages or 0
        )
        progress.update_percentage()  # Calculate percentage
        db.session.add(progress)
    
    db.session.commit()
    return jsonify({'success': True, 'message': 'Progress updated'})
@main.route('/api/rate_comic', methods=['POST'])
@login_required
def api_rate_comic():
    """Rate a comic via AJAX"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'success': False, 'error': 'Invalid JSON data'}), 400
    
    comic_id = data.get('comic_id')
    score = data.get('score') or data.get('rating')
    
    if not comic_id or not score:
        return jsonify({'success': False, 'error': 'Missing comic_id or score'}), 400
    
    score = int(score)
    if not 1 <= score <= 5:
        return jsonify({'success': False, 'error': 'Score must be between 1 and 5'}), 400
    
    rating = Rating.query.filter_by(user_id=current_user.id, comic_id=comic_id).first()
    
    if rating:
        rating.score = score
    else:
        rating = Rating(user_id=current_user.id, comic_id=comic_id, score=score)
        db.session.add(rating)
    
    db.session.commit()
    
    # Update comic's average rating
    comic = Comic.query.get(comic_id)
    if comic:
        comic.update_rating()
        
    return jsonify({
        'success': True, 
        'new_average': round(comic.average_rating, 1) if comic else 0,
        'total_ratings': comic.ratings.count() if comic else 0
    })


# ============================
# Admin Routes
# ============================

@main.route('/admin')
@main.route('/admin/dashboard')
@login_required
def admin_dashboard():
    """Admin dashboard overview"""
    if not current_user.is_admin:
        return redirect(url_for('main.home'))
    
    if current_user.check_password('admin123'):
        flash('SECURITY WARNING: Your account is currently using the default password ("admin123"). Please change it immediately to secure your server.', 'danger')
    
    avg_rating = db.session.query(db.func.avg(Rating.score)).scalar() or 0.0
    
    stats = {
        'total_comics': Comic.query.count(),
        'total_users': User.query.count(),
        'total_views': db.session.query(db.func.sum(Comic.view_count)).scalar() or 0,
        'total_ratings': Rating.query.count(),
        'avg_rating': avg_rating,
        'total_categories': Category.query.count(),
        'recent_uploads': Comic.query.order_by(Comic.created_at.desc()).limit(5).all()
    }
    
    recent_comics = stats['recent_uploads']
    recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
    
    return render_template('admin/admin_dashboard.html', 
                         stats=stats, 
                         recent_comics=recent_comics,
                         recent_users=recent_users)


@main.route('/admin/analytics')
@login_required
def admin_analytics():
    """Admin analytics dashboard"""
    if not current_user.is_admin:
        return redirect(url_for('main.home'))
    
    # Get analytics statistics
    from datetime import timedelta
    
    # Basic stats
    stats = {
        'total_comics': Comic.query.count(),
        'total_users': User.query.count(),
        'total_ratings': Rating.query.count(),
        'total_views': db.session.query(db.func.sum(Comic.view_count)).scalar() or 0,
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
                            
    # Generate Chart Data
    import json
    
    # 1. User Growth (last 30 days cumulative)
    user_growth_labels = []
    user_growth_data = []
    for i in range(29, -1, -1):
        date = (datetime.utcnow() - timedelta(days=i)).date()
        cum_count = User.query.filter(db.func.date(User.created_at) <= date).count()
        user_growth_labels.append(date.strftime('%b %d'))
        user_growth_data.append(cum_count)
        
    chart_data_user = {
        'labels': user_growth_labels,
        'data': user_growth_data
    }
    
    # 2. Category Distribution
    category_labels = []
    category_data = []
    for cat in Category.query.all():
        count = Comic.query.filter_by(category=cat.name).count()
        if count > 0:
            category_labels.append(cat.name)
            category_data.append(count)
            
    if not category_labels:
        category_labels = ['General']
        category_data = [0]
        
    chart_data_category = {
        'labels': category_labels,
        'data': category_data
    }
    
    # 3. Reading Activity (last 7 days)
    reading_labels = []
    reading_data = []
    for i in range(6, -1, -1):
        date = (datetime.utcnow() - timedelta(days=i)).date()
        count = ReadingProgress.query.filter(db.func.date(ReadingProgress.last_read_at) == date).count()
        reading_labels.append(date.strftime('%a'))
        reading_data.append(count)
        
    chart_data_reading = {
        'labels': reading_labels,
        'data': reading_data
    }
    
    # 4. Rating Distribution
    rating_labels = ['1 Star', '2 Stars', '3 Stars', '4 Stars', '5 Stars']
    rating_data = [
        Rating.query.filter_by(score=1).count(),
        Rating.query.filter_by(score=2).count(),
        Rating.query.filter_by(score=3).count(),
        Rating.query.filter_by(score=4).count(),
        Rating.query.filter_by(score=5).count(),
    ]
    
    chart_data_rating = {
        'labels': rating_labels,
        'data': rating_data
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


@main.route('/admin/comics')
@login_required
def admin_comics():
    """Admin comic management"""
    if not current_user.is_admin:
        return redirect(url_for('main.home'))
    
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    
    query = Comic.query
    if search:
        query = query.filter(Comic.title.ilike(f'%{search}%'))
        
    pagination = query.order_by(Comic.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    
    return render_template('admin/comics.html', 
                         comics=pagination, 
                         pagination=pagination,
                         categories=Category.query.all())


@main.route('/admin/comics/new', methods=['GET', 'POST'])
@login_required
def admin_comic_create():
    """Create new comic manually or via uploader"""
    if not current_user.is_admin:
        return redirect(url_for('main.home'))
    
    if request.method == 'POST':
        category_id = request.form.get('category_id')
        category_name = 'General'
        if category_id:
            cat = Category.query.get(category_id)
            if cat:
                category_name = cat.name

        def clean_str(s):
            return bleach.clean(s) if s else s
            
        comic = Comic(
            title=clean_str(request.form.get('title')),
            author=clean_str(request.form.get('author')),
            artist=clean_str(request.form.get('artist')),
            description=clean_str(request.form.get('description')),
            category=category_name,
            language=request.form.get('language', 'English'),
            visibility=request.form.get('visibility', 'public'),
            pdf_file=format_storage_ref(request.form.get('local_path')),
            cover_image=format_storage_ref(request.form.get('cover_path')),
            download_link=request.form.get('download_link'),
            uploader_id=current_user.id
        )
        
        # Handle manual cover upload if provided (overrides AI extracted cover)
        if 'cover' in request.files:
            file = request.files['cover']
            if file and file.filename:
                cloud_enabled = Setting.get('cloud_storage_enabled') == '1'
                userhash = Setting.get('catbox_userhash', '')
                if cloud_enabled:
                    service = CatboxService(userhash=userhash)
                    cover_cloud_url = service.upload_file(file.read(), filename=f"cover_{uuid.uuid4().hex[:8]}_{secure_filename(file.filename)}")
                    if cover_cloud_url:
                        comic.cover_image = cover_cloud_url
                else:
                    filename = secure_filename(file.filename)
                    unique_filename = f"{uuid.uuid4().hex[:8]}_{filename}"
                    file.save(os.path.join(current_app.static_folder, 'uploads', 'covers', unique_filename))
                    comic.cover_image = unique_filename
        
        db.session.add(comic)
        db.session.commit()
        
        # Save tags
        tags_str = request.form.get('tags', '')
        if tags_str:
            tags_list = [t.strip() for t in tags_str.split(',') if t.strip()]
            for t in tags_list:
                db.session.add(ComicTag(comic_id=comic.id, tag=t))
            db.session.commit()
        
        # Proactively extract pages immediately after posting
        if comic.pdf_file:
            cloud_enabled = Setting.get('cloud_storage_enabled') == '1'
            userhash = Setting.get('catbox_userhash', '')
            try:
                config_dict = {
                    'COVERS_FOLDER': os.path.join(current_app.static_folder, 'uploads', 'covers'),
                    'CLOUD_STORAGE_ENABLED': cloud_enabled,
                    'CATBOX_USERHASH': userhash
                }
                uploader = create_uploader_from_config(config_dict)
                
                if comic.pdf_file.startswith(('http://', 'https://')):
                    pdf_input = comic.pdf_file
                else:
                    pdf_input = os.path.join(current_app.static_folder, 'uploads', 'comics', comic.pdf_file)
                
                # Check if pages are already in ComicPage or need extracting
                existing_pages = ComicPage.query.filter_by(comic_id=comic.id).count()
                if existing_pages == 0:
                    page_urls = uploader.extract_pages(
                        pdf_input=pdf_input,
                        comic_id=str(comic.id),
                        upload_to_catbox=cloud_enabled,
                        catbox_userhash=userhash
                    )
                    if cloud_enabled and page_urls:
                        for idx, purl in enumerate(page_urls):
                            db.session.add(ComicPage(comic_id=comic.id, page_number=idx + 1, image_url=purl))
                        db.session.commit()
                        
                        # Create Catbox Album grouping all comic files together
                        if userhash:
                            try:
                                album_files = [comic.pdf_file, comic.cover_image] + page_urls
                                catbox_svc = CatboxService(userhash=userhash)
                                album_url = catbox_svc.create_album(
                                    title=comic.title,
                                    files=album_files,
                                    desc=f"{comic.title} by {comic.author or 'Unknown'}"
                                )
                                if album_url:
                                    comic.album_url = album_url
                                    db.session.commit()
                            except Exception as album_err:
                                print(f"Catbox album creation error: {album_err}")
            except Exception as e:
                print(f"Proactive extraction failed: {str(e)}")
        
        flash('Comic created successfully and pages extracted!', 'success')
        return redirect(url_for('main.admin_comics'))
    
    categories = Category.query.all()
    return render_template('admin/admin_add_comic.html', categories=categories)


@main.route('/admin/comics/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def admin_comic_edit(id):
    """Edit existing comic"""
    if not current_user.is_admin:
        return redirect(url_for('main.home'))
    
    comic = Comic.query.get_or_404(id)
    
    if request.method == 'POST':
        def clean_str(s):
            return bleach.clean(s) if s else s
            
        comic.title = clean_str(request.form.get('title'))
        comic.author = clean_str(request.form.get('author'))
        comic.artist = clean_str(request.form.get('artist'))
        comic.description = clean_str(request.form.get('description'))
        
        # Save episode as integer numeric only
        episode_val = request.form.get('episode')
        if episode_val:
            try:
                comic.episode = str(int(str(episode_val).strip()))
            except ValueError:
                comic.episode = None
        else:
            comic.episode = None
            
        comic.category = request.form.get('category')
        comic.language = request.form.get('language', 'English')
        comic.visibility = request.form.get('visibility')
        comic.is_featured = True if request.form.get('is_featured') == '1' else False
        comic.download_link = request.form.get('download_link')
        
        # Update tags
        tags_str = request.form.get('tags', '')
        if tags_str:
            # Clear existing tags
            ComicTag.query.filter_by(comic_id=comic.id).delete()
            # Add new tags
            tags_list = [t.strip() for t in tags_str.split(',') if t.strip()]
            for t in tags_list:
                db.session.add(ComicTag(comic_id=comic.id, tag=t))
        
        # Update cover if new one provided
        if 'cover' in request.files:
            file = request.files['cover']
            if file and allowed_file(file.filename):
                cloud_enabled = Setting.get('cloud_storage_enabled') == '1'
                userhash = Setting.get('catbox_userhash', '')
                if cloud_enabled:
                    service = CatboxService(userhash=userhash)
                    cover_cloud_url = service.upload_file(file.read(), filename=f"cover_{uuid.uuid4().hex[:8]}_{secure_filename(file.filename)}")
                    if cover_cloud_url:
                        comic.cover_image = cover_cloud_url
                else:
                    filename = secure_filename(file.filename)
                    unique_filename = f"{uuid.uuid4().hex[:8]}_{filename}"
                    file.save(os.path.join(current_app.static_folder, 'uploads', 'covers', unique_filename))
                    comic.cover_image = unique_filename
        
        db.session.commit()
        flash('Comic updated successfully!', 'success')
        return redirect(url_for('main.admin_comics'))
    
    categories = Category.query.all()
    return render_template('admin/admin_edit_comic.html', comic=comic, categories=categories)


@main.route('/admin/comics/<int:id>/delete', methods=['POST'])
@login_required
def admin_comic_delete(id):
    """Delete a comic"""
    if not current_user.is_admin:
        return redirect(url_for('main.home'))
    
    comic = Comic.query.get_or_404(id)
    if comic.album_url and Setting.get('cloud_storage_enabled') == '1':
        userhash = Setting.get('catbox_userhash', '')
        if userhash:
            try:
                catbox_svc = CatboxService(userhash=userhash)
                catbox_svc.delete_album(comic.album_url)
            except Exception:
                pass
    db.session.delete(comic)
    db.session.commit()
    flash('Comic deleted successfully!', 'success')
    return redirect(url_for('main.admin_comics'))


@main.route('/admin/comic/<int:comic_id>/chapters')
@login_required
def admin_chapters(comic_id):
    """Manage chapters for a specific comic"""
    if not current_user.is_admin:
        return redirect(url_for('main.home'))
    
    comic = Comic.query.get_or_404(comic_id)
    chapters = Chapter.query.filter_by(comic_id=comic_id).order_by(Chapter.chapter_number.asc()).all()
    
    return render_template('admin/chapters.html', comic=comic, chapters=chapters)


@main.route('/admin/users')
@login_required
def admin_users():
    """Admin user management list"""
    if not current_user.is_admin:
        return redirect(url_for('main.home'))
    
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    
    query = User.query
    if search:
        query = query.filter((User.username.ilike(f'%{search}%')) | (User.email.ilike(f'%{search}%')))
        
    pagination = query.order_by(User.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    
    return render_template('admin/users.html', users=pagination, pagination=pagination)


@main.route('/admin/users/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def admin_user_edit(id):
    """Edit user details from admin panel"""
    if not current_user.is_admin:
        return redirect(url_for('main.home'))
    
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
        return redirect(url_for('main.admin_users'))
    
    return render_template('admin/user_edit.html', user=user)


@main.route('/admin/users/<int:id>/delete', methods=['POST'])
@login_required
def admin_user_delete(id):
    """Delete a user account"""
    if not current_user.is_admin:
        return redirect(url_for('main.home'))
    
    user = User.query.get_or_404(id)
    if user.id == current_user.id:
        flash('You cannot delete your own admin account.', 'danger')
    else:
        db.session.delete(user)
        db.session.commit()
        flash('User deleted successfully!', 'success')
        
    return redirect(url_for('main.admin_users'))


@main.route('/admin/ads')
@login_required
def admin_ads():
    """Manage advertisements"""
    if not current_user.is_admin:
        return redirect(url_for('main.home'))
    
    ads = Ad.query.order_by(Ad.created_at.desc()).all()
    return render_template('admin/ads.html', ads=ads)


@main.route('/admin/ads/new', methods=['GET', 'POST'])
@login_required
def admin_ad_create():
    """Create new advertisement"""
    if not current_user.is_admin:
        return redirect(url_for('main.home'))
    
    if request.method == 'POST':
        ad = Ad(
            title=request.form.get('title'),
            placement=request.form.get('placement'),
            ad_code=request.form.get('ad_code'),
            is_active=request.form.get('is_active') == 'on'
        )
        db.session.add(ad)
        db.session.commit()
        flash('Ad created successfully!', 'success')
        return redirect(url_for('main.admin_ads'))
    
    return render_template('admin/ad_edit.html', ad=None)


@main.route('/admin/ads/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def admin_ad_edit(id):
    """Edit advertisement"""
    if not current_user.is_admin:
        return redirect(url_for('main.home'))
    
    ad = Ad.query.get_or_404(id)
    
    if request.method == 'POST':
        ad.title = request.form.get('title')
        ad.placement = request.form.get('placement')
        ad.ad_code = request.form.get('ad_code')
        ad.is_active = request.form.get('is_active') == 'on'
        
        db.session.commit()
        flash('Ad updated successfully!', 'success')
        return redirect(url_for('main.admin_ads'))
    
    return render_template('admin/ad_edit.html', ad=ad)


@main.route('/admin/ads/<int:id>/delete', methods=['POST'])
@login_required
def admin_ad_delete(id):
    """Delete advertisement"""
    if not current_user.is_admin:
        return redirect(url_for('main.home'))
    
    ad = Ad.query.get_or_404(id)
    db.session.delete(ad)
    db.session.commit()
    flash('Ad deleted successfully!', 'success')
    return redirect(url_for('main.admin_ads'))


@main.route('/admin/categories')
@login_required
def admin_categories():
    """Manage categories"""
    if not current_user.is_admin:
        return redirect(url_for('main.home'))
    
    categories_list = Category.query.all()
    categories = []
    for cat in categories_list:
        count = Comic.query.filter_by(category=cat.name).count()
        categories.append((cat, count))
    return render_template('admin/categories.html', categories=categories)


@main.route('/admin/categories/new', methods=['GET', 'POST'])
@login_required
def admin_category_create():
    """Create new category"""
    if not current_user.is_admin:
        return redirect(url_for('main.home'))
    
    if request.method == 'POST':
        name = request.form.get('category')
        if not name:
            flash('Category name is required.', 'danger')
            return render_template('admin/category_form.html')
            
        slug = name.lower().replace(' ', '-')
        # Check if already exists
        if Category.query.filter_by(name=name).first() or Category.query.filter_by(slug=slug).first():
            flash('Category with this name already exists.', 'danger')
            return render_template('admin/category_form.html')
            
        category = Category(
            name=name,
            slug=slug,
            icon='fas fa-book',
            description=''
        )
        db.session.add(category)
        db.session.commit()
        flash('Category created successfully!', 'success')
        return redirect(url_for('main.admin_categories'))
        
    return render_template('admin/category_form.html')


def sync_tags():
    """Sync tags between ComicTag and Tag models"""
    try:
        unique_tags = db.session.query(ComicTag.tag).distinct().all()
        unique_tags = [t[0].strip() for t in unique_tags if t[0]]
        for tag_name in unique_tags:
            if not Tag.query.filter_by(name=tag_name).first():
                new_tag = Tag(name=tag_name)
                db.session.add(new_tag)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error syncing tags: {e}")


@main.route('/admin/tags')
@login_required
def admin_tags():
    """Manage tags"""
    if not current_user.is_admin:
        return redirect(url_for('main.home'))
    
    sync_tags()
    
    tags_list = Tag.query.all()
    tags = []
    for tag in tags_list:
        count = ComicTag.query.filter_by(tag=tag.name).count()
        tags.append((tag, count))
    return render_template('admin/tags.html', tags=tags)


@main.route('/admin/tags/new', methods=['GET', 'POST'])
@login_required
def admin_tag_create():
    """Create new tag"""
    if not current_user.is_admin:
        return redirect(url_for('main.home'))
        
    if request.method == 'POST':
        name = request.form.get('tag')
        if not name:
            flash('Tag name is required.', 'danger')
            return render_template('admin/tag_form.html')
            
        name = name.strip()
        if Tag.query.filter_by(name=name).first():
            flash('Tag already exists.', 'danger')
            return render_template('admin/tag_form.html')
            
        tag = Tag(name=name)
        db.session.add(tag)
        db.session.commit()
        flash('Tag created successfully!', 'success')
        return redirect(url_for('main.admin_tags'))
        
    return render_template('admin/tag_form.html')


@main.route('/admin/tags/<int:id>/delete', methods=['POST'])
@login_required
def admin_tag_delete(id):
    """Delete a tag"""
    if not current_user.is_admin:
        return redirect(url_for('main.home'))
        
    tag = Tag.query.get_or_404(id)
    # Remove from ComicTag too
    ComicTag.query.filter_by(tag=tag.name).delete()
    
    db.session.delete(tag)
    db.session.commit()
    flash('Tag deleted successfully!', 'success')
    return redirect(url_for('main.admin_tags'))


@main.route('/admin/settings', methods=['GET', 'POST'])
@login_required
def admin_settings():
    """Application settings page"""
    if not current_user.is_admin:
        return redirect(url_for('main.home'))
    
    if request.method == 'POST':
        section = request.form.get('section', 'all')
        
        if section == 'llm':
            Setting.set('llm_base_url', request.form.get('llm_base_url', ''), 'Base URL for LLM API')
            Setting.set('llm_api_key', request.form.get('llm_api_key', ''), 'API key for LLM')
            Setting.set('llm_model', request.form.get('llm_model', ''), 'Model name for LLM')
            Setting.set('llm_use_local', '1' if request.form.get('llm_use_local') else '0', 'Use local LLM')
            flash('LLM Configuration saved!', 'success')
            
        elif section == 'upfiles':
            Setting.set('upfiles_endpoint', request.form.get('upfiles_endpoint', 'https://api.upfiles.com/upload'), 'UpFiles API endpoint')
            Setting.set('upfiles_token', request.form.get('upfiles_token', ''), 'UpFiles API token')
            flash('Upload Configuration saved!', 'success')
            
        elif section == 'catbox':
            Setting.set('cloud_storage_enabled', '1' if request.form.get('cloud_storage_enabled') else '0', 'Enable Catbox cloud storage')
            Setting.set('catbox_userhash', request.form.get('catbox_userhash', '').strip(), 'Catbox account userhash')
            flash('Cloud Storage (Catbox.moe) settings saved!', 'success')
            
        elif section == 'site':
            Setting.set('site_name', request.form.get('site_name', 'ComicVault'), 'Site name')
            flash('Site Settings saved!', 'success')
            
        return redirect(url_for('main.admin_settings'))
    
    # Load all settings into a dict with sensitive values decrypted for display
    settings = Setting.get_all_dict()
    return render_template('admin/settings.html', settings=settings)


# ============================
# Admin Tools & API
# ============================

@main.route('/admin/test_catbox', methods=['POST'])
@login_required
def admin_test_catbox():
    """Test Catbox.moe API connection and validate userhash"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    userhash = Setting.get('catbox_userhash', '')
    if request.is_json:
        data = request.get_json()
        if data and 'catbox_userhash' in data:
            userhash = data.get('catbox_userhash', '')
            
    service = CatboxService(userhash=userhash)
    success, message = service.test_connection(userhash=userhash)
    return jsonify({'success': success, 'message': message})


@main.route('/admin/migrate_to_cloud', methods=['POST'])
@login_required
def admin_migrate_to_cloud():
    """Migrate local comic assets (covers, PDFs, extracted pages) to Catbox.moe"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    userhash = Setting.get('catbox_userhash', '')
    service = CatboxService(userhash=userhash)
    
    # Test connection first
    ok, msg = service.test_connection()
    if not ok:
        return jsonify({'success': False, 'message': f'Cannot reach Catbox: {msg}'}), 400
    
    comics = Comic.query.all()
    migrated_count = 0
    covers_migrated = 0
    pdfs_migrated = 0
    pages_migrated = 0
    errors = []
    
    for comic in comics:
        try:
            # 1. Migrate cover image
            if comic.cover_image and not comic.cover_image.startswith(('http://', 'https://')):
                local_cover = os.path.join(current_app.static_folder, 'uploads', 'covers', comic.cover_image)
                if os.path.exists(local_cover):
                    cloud_cover_url = service.upload_file(local_cover)
                    if cloud_cover_url:
                        comic.cover_image = cloud_cover_url
                        covers_migrated += 1
                        try:
                            os.remove(local_cover)
                        except Exception:
                            pass
            
            # 2. Migrate raw comic PDF
            if comic.pdf_file and not comic.pdf_file.startswith(('http://', 'https://')):
                local_pdf = os.path.join(current_app.static_folder, 'uploads', 'comics', comic.pdf_file)
                if os.path.exists(local_pdf):
                    cloud_pdf_url = service.upload_file(local_pdf)
                    if cloud_pdf_url:
                        comic.pdf_file = cloud_pdf_url
                        pdfs_migrated += 1
                        try:
                            os.remove(local_pdf)
                        except Exception:
                            pass
            
            # 3. Migrate extracted pages
            local_pages_dir = os.path.join(current_app.static_folder, 'uploads', 'pages', str(comic.id))
            if os.path.exists(local_pages_dir):
                page_files = sorted([f for f in os.listdir(local_pages_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))])
                if page_files:
                    # Clean existing ComicPage rows for this comic
                    ComicPage.query.filter_by(comic_id=comic.id).delete()
                    
                    for idx, pf in enumerate(page_files):
                        if idx > 0:
                            import time
                            time.sleep(0.3)  # Gentle pacing to avoid burst rate-limiting
                        page_path = os.path.join(local_pages_dir, pf)
                        page_cloud_url = service.upload_file(page_path)
                        if page_cloud_url:
                            db.session.add(ComicPage(comic_id=comic.id, page_number=idx + 1, image_url=page_cloud_url))
                            pages_migrated += 1
                            try:
                                os.remove(page_path)
                            except Exception:
                                pass
                    try:
                        os.rmdir(local_pages_dir)
                    except Exception:
                        pass
            
            db.session.commit()
            migrated_count += 1
        except Exception as e:
            errors.append(f"Comic #{comic.id} ('{comic.title}'): {str(e)}")
            db.session.rollback()
            
    return jsonify({
        'success': True,
        'message': f"Migration complete! Processed {migrated_count} comics ({covers_migrated} covers, {pdfs_migrated} PDFs, {pages_migrated} pages).",
        'stats': {
            'comics': migrated_count,
            'covers': covers_migrated,
            'pdfs': pdfs_migrated,
            'pages': pages_migrated,
            'errors': errors
        }
    })


@main.route('/admin/test_llm', methods=['POST'])
@login_required
def admin_test_llm():
    """Test LLM connection"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
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
        
        # Add /chat/completions if missing
        url = base_url.rstrip('/')
        if not url.endswith('/chat/completions'):
            url += '/chat/completions'
            
        response = requests.post(
            url,
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
            return jsonify({'success': False, 'message': f'API returned status {response.status_code}: {response.text}'})
    
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@main.route('/admin/test_upfiles', methods=['POST'])
@login_required
def admin_test_upfiles():
    """Test UpFiles connection"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    import requests
    import io
    
    token = Setting.get('upfiles_token')
    endpoint = Setting.get('upfiles_endpoint', 'https://api.upfiles.com/upload')
    
    if not token:
        return jsonify({'success': False, 'message': 'UpFiles token not configured'})
    
    try:
        test_file = io.BytesIO(b'test content')
        # Use tuple to ensure order: token then file
        files = [
            ('token', (None, token)),
            ('file', ('test.txt', test_file, 'text/plain'))
        ]
        
        response = requests.post(endpoint, files=files, timeout=30)
        result = response.json()
        
        if result.get('status') == 'success':
            return jsonify({'success': True, 'message': 'Connection successful', 'url': result.get('url')})
        else:
            return jsonify({'success': False, 'message': result.get('message', 'Unknown error')})
    
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@main.route('/admin/unified_upload', methods=['POST'])
@login_required
def admin_unified_upload():
    """Unified upload and analysis endpoint"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'No PDF file provided'}), 400
    
    pdf_file = request.files['file']
    if pdf_file.filename == '':
        return jsonify({'success': False, 'message': 'No file selected'}), 400
    
    try:
        # Load config for uploader
        cloud_enabled = Setting.get('cloud_storage_enabled') == '1'
        userhash = Setting.get('catbox_userhash', '')
        config_dict = {
            'UPLOAD_FOLDER': os.path.join(current_app.static_folder, 'uploads', 'comics'),
            'COVERS_FOLDER': os.path.join(current_app.static_folder, 'uploads', 'covers'),
            'UPFILES_API_KEY': Setting.get('upfiles_token'),
            'UPFILES_ENDPOINT': Setting.get('upfiles_endpoint', 'https://api.upfiles.com/upload'),
            'AI_API_KEY': Setting.get('llm_api_key'),
            'AI_MODEL': Setting.get('llm_model', 'gpt-4-vision-preview'),
            'AI_BASE_URL': Setting.get('llm_base_url'),
            'USE_LOCAL_LLM': Setting.get('llm_use_local') == '1',
            'CLOUD_STORAGE_ENABLED': cloud_enabled,
            'CATBOX_USERHASH': userhash
        }
        
        uploader = create_uploader_from_config(config_dict)
        
        # Check if we should upload to upfiles now
        should_upload = request.form.get('upload_to_upfiles', 'true').lower() == 'true'
        
        # Run upload workflow
        result = uploader.upload_comic(
            file_stream=pdf_file,
            filename=pdf_file.filename,
            extract_metadata=True,
            upload_to_upfiles=should_upload
        )
        
        if result['success']:
            metadata = result.get('metadata') or {}
            
            return jsonify({
                'success': True, 
                'message': 'Comic processed successfully!',
                'data': {
                    'metadata': metadata,
                    'local_path': format_storage_ref(result['local_path']),
                    'cover_path': format_storage_ref(result.get('cover_path')),
                    'cover_url': result.get('cover_url'),
                    'upfiles_url': result.get('upfiles_url')
                }
            })
        else:
            return jsonify({'success': False, 'message': f"Process failed: {', '.join(result['errors'])}"}), 500
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@main.route('/admin/upload_to_host', methods=['POST'])
@login_required
def admin_upload_to_host():
    """Upload a locally stored or cloud-hosted file to UpFiles on demand"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    data = request.get_json() or {}
    local_filename = data.get('local_path')
    
    if not local_filename:
        return jsonify({'success': False, 'message': 'No local path or URL provided'}), 400
    
    try:
        config_dict = {
            'UPFILES_API_KEY': Setting.get('upfiles_token'),
            'UPFILES_ENDPOINT': Setting.get('upfiles_endpoint', 'https://api.upfiles.com/upload')
        }
        uploader = create_uploader_from_config(config_dict)
        
        # Check if local_filename is an absolute cloud URL (e.g. Catbox)
        if local_filename.startswith(('http://', 'https://')):
            from security_utils import is_safe_url
            if not is_safe_url(local_filename):
                return jsonify({'success': False, 'message': 'Invalid or restricted remote URL'}), 400
                
            from catbox_service import get_catbox_session
            session = get_catbox_session()
            resp = session.get(local_filename, timeout=120)
            if resp.status_code == 200 and resp.content:
                fname = os.path.basename(local_filename.split('?')[0])
                if not fname.lower().endswith('.pdf'):
                    fname += '.pdf'
                upfiles_result = uploader._upload_to_upfiles(resp.content, filename=fname)
            else:
                return jsonify({'success': False, 'message': f'Failed to retrieve file from cloud storage ({resp.status_code})'}), 400
        else:
            # Secure the filename and build full local path
            from security_utils import safe_join_path
            comics_dir = os.path.join(current_app.static_folder, 'uploads', 'comics')
            local_path = safe_join_path(comics_dir, local_filename)
            
            if not local_path or not os.path.exists(local_path):
                return jsonify({'success': False, 'message': f'File not found: {local_filename}'}), 404
            
            upfiles_result = uploader._upload_to_upfiles(local_path)
        
        if upfiles_result.get('success'):
            return jsonify({
                'success': True,
                'upfiles_url': upfiles_result.get('url')
            })
        else:
            return jsonify({
                'success': False,
                'message': upfiles_result.get('message', 'Upload failed')
            })
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@main.route('/admin/bulk_upload', methods=['GET'])
@login_required
def admin_bulk_upload():
    """Bulk upload page"""
    if not current_user.is_admin:
        return redirect(url_for('main.home'))
    categories = Category.query.all()
    return render_template('admin/admin_bulk_upload.html', categories=categories)


@main.route('/admin/bulk_upload_file', methods=['POST'])
@login_required
def admin_bulk_upload_file():
    """Process a single file in the bulk upload queue and save as draft"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'No file provided'}), 400
        
    pdf_file = request.files['file']
    if pdf_file.filename == '':
        return jsonify({'success': False, 'message': 'No file selected'}), 400
        
    try:
        # Load config for uploader
        cloud_enabled = Setting.get('cloud_storage_enabled') == '1'
        userhash = Setting.get('catbox_userhash', '')
        config_dict = {
            'UPLOAD_FOLDER': os.path.join(current_app.static_folder, 'uploads', 'comics'),
            'COVERS_FOLDER': os.path.join(current_app.static_folder, 'uploads', 'covers'),
            'UPFILES_API_KEY': Setting.get('upfiles_token'),
            'UPFILES_ENDPOINT': Setting.get('upfiles_endpoint', 'https://api.upfiles.com/upload'),
            'AI_API_KEY': Setting.get('llm_api_key'),
            'AI_MODEL': Setting.get('llm_model', 'gpt-4-vision-preview'),
            'AI_BASE_URL': Setting.get('llm_base_url'),
            'USE_LOCAL_LLM': Setting.get('llm_use_local') == '1',
            'CLOUD_STORAGE_ENABLED': cloud_enabled,
            'CATBOX_USERHASH': userhash
        }
        
        uploader = create_uploader_from_config(config_dict)
        
        # Decide if we should upload to upfiles (same as single uploader, if key exists)
        should_upload = bool(Setting.get('upfiles_token'))
        
        # Run AI upload workflow
        result = uploader.upload_comic(
            file_stream=pdf_file,
            filename=pdf_file.filename,
            extract_metadata=True,
            upload_to_upfiles=should_upload
        )
        
        if not result.get('local_path'):
            return jsonify({'success': False, 'message': f"Process failed: {', '.join(result['errors'])}"}), 500
            
        metadata = result.get('metadata') or {}
        
        # Extract fields
        title = metadata.get('title') or os.path.splitext(pdf_file.filename)[0].replace('_', ' ')
        author = metadata.get('author') or 'Unknown'
        artist = metadata.get('artist') or 'Unknown'
        description = metadata.get('description') or ''
        language = metadata.get('language') or 'English'
        
        episode = metadata.get('episode')
        if episode is not None:
            try:
                episode = str(int(float(episode)))
            except (ValueError, TypeError):
                episode = None
        
        # Match category name to database
        category_name = 'General'
        if metadata.get('category'):
            matched_cat = Category.query.filter(Category.name.ilike(metadata.get('category'))).first()
            if matched_cat:
                category_name = matched_cat.name
                
        # Create Comic in Draft status
        comic = Comic(
            title=title,
            episode=episode,
            author=author,
            artist=artist,
            description=description,
            category=category_name,
            language=language,
            visibility='draft',
            is_published=False,
            pdf_file=format_storage_ref(result['local_path']),
            cover_image=format_storage_ref(result.get('cover_path')),
            download_link=result.get('upfiles_url'),
            uploader_id=current_user.id
        )
        
        db.session.add(comic)
        db.session.commit()
        
        # Save tags
        tags = metadata.get('tags') or []
        if tags:
            for t in tags:
                db.session.add(ComicTag(comic_id=comic.id, tag=t.strip()))
            db.session.commit()
            
        # Extract all pages
        if comic.pdf_file:
            try:
                pdf_input = result.get('pdf_bytes') or comic.pdf_file
                page_urls = uploader.extract_pages(
                    pdf_input=pdf_input,
                    comic_id=str(comic.id),
                    upload_to_catbox=cloud_enabled,
                    catbox_userhash=userhash
                )
                if cloud_enabled and page_urls:
                    for idx, purl in enumerate(page_urls):
                        db.session.add(ComicPage(comic_id=comic.id, page_number=idx + 1, image_url=purl))
                    db.session.commit()
                    
                    if userhash:
                        try:
                            album_files = [comic.pdf_file, comic.cover_image] + page_urls
                            catbox_svc = CatboxService(userhash=userhash)
                            album_url = catbox_svc.create_album(
                                title=comic.title,
                                files=album_files,
                                desc=f"{comic.title} by {comic.author or 'Unknown'}"
                            )
                            if album_url:
                                comic.album_url = album_url
                                db.session.commit()
                        except Exception as album_err:
                            print(f"Catbox album creation error: {album_err}")
            except Exception as e:
                print(f"Page extraction failed: {str(e)}")
                    
        return jsonify({
            'success': True,
            'message': 'Comic processed and saved as draft!',
            'comic_id': comic.id,
            'title': comic.title,
            'metadata': metadata
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ============================
# Bookmark API Endpoints
# ============================

@main.route('/api/bookmarks', methods=['POST'])
@login_required
@limiter.limit("30 per minute")
def create_bookmark():
    """Create a new bookmark"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'success': False, 'message': 'Invalid JSON data'}), 400
    
    comic_id = data.get('comic_id')
    chapter_id = data.get('chapter_id')
    page_number = data.get('page_number')
    from security_utils import sanitize_plain_text
    note = sanitize_plain_text(data.get('note', ''), max_length=255)
    
    if not all([comic_id, page_number]):
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400
    
    # Check for duplicate bookmark at same location
    existing = Bookmark.query.filter_by(
        user_id=current_user.id,
        comic_id=comic_id,
        page_number=page_number
    ).filter(
        Bookmark.chapter_id == chapter_id if chapter_id else True
    ).first()
    
    if existing:
        return jsonify({'success': False, 'message': 'Bookmark already exists at this page'}), 409
    
    bookmark = Bookmark(
        user_id=current_user.id,
        comic_id=comic_id,
        chapter_id=chapter_id,
        page_number=page_number,
        note=note
    )
    db.session.add(bookmark)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'bookmark': {
            'id': bookmark.id,
            'page_number': bookmark.page_number,
            'note': bookmark.note,
            'created_at': bookmark.created_at.isoformat() if bookmark.created_at else None
        }
    })


@main.route('/api/bookics/<int:comic_id>')
@login_required
def get_comic_bookmarks(comic_id):
    """Get all bookmarks for a comic"""
    bookmarks = Bookmark.query.filter_by(
        user_id=current_user.id,
        comic_id=comic_id
    ).order_by(Bookmark.page_number).all()
    
    return jsonify({
        'success': True,
        'bookmarks': [{
            'id': b.id,
            'chapter_id': b.chapter_id,
            'page_number': b.page_number,
            'note': b.note,
            'created_at': b.created_at.isoformat() if b.created_at else None
        } for b in bookmarks]
    })


@main.route('/api/bookmarks/<int:bookmark_id>', methods=['DELETE'])
@login_required
def delete_bookmark(bookmark_id):
    """Delete a bookmark"""
    bookmark = Bookmark.query.filter_by(
        id=bookmark_id,
        user_id=current_user.id
    ).first()
    
    if not bookmark:
        return jsonify({'success': False, 'message': 'Bookmark not found'}), 404
    
    db.session.delete(bookmark)
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'Bookmark deleted'})


# ============================
# Reading Progress API Endpoints
# ============================

@main.route('/api/reading-progress', methods=['POST'])
@login_required
def save_reading_progress():
    """Save reading progress for a comic"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'success': False, 'message': 'Invalid JSON data'}), 400
    
    comic_id = data.get('comic_id')
    chapter_id = data.get('chapter_id')
    page_number = data.get('page_number')
    total_pages = data.get('total_pages')
    time_spent = data.get('time_spent', 0)
    
    if not comic_id or page_number is None:
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400
    
    progress = ReadingProgress.query.filter_by(
        user_id=current_user.id,
        comic_id=comic_id,
        chapter_id=chapter_id
    ).first()
    
    if progress:
        progress.current_page = page_number
        progress.total_pages = total_pages or progress.total_pages
        progress.time_spent = (progress.time_spent or 0) + time_spent
        progress.last_read = datetime.utcnow()
        progress.update_percentage()
    else:
        progress = ReadingProgress(
            user_id=current_user.id,
            comic_id=comic_id,
            chapter_id=chapter_id,
            current_page=page_number,
            total_pages=total_pages,
            time_spent=time_spent
        )
        db.session.add(progress)
    
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'Progress saved'})


@main.route('/api/reading-progress/<int:comic_id>')
@login_required
def get_reading_progress(comic_id):
    """Get reading progress for a comic"""
    progress = ReadingProgress.query.filter_by(
        user_id=current_user.id,
        comic_id=comic_id
    ).order_by(ReadingProgress.last_read_at.desc()).first()
    
    if not progress:
        return jsonify({'success': False, 'message': 'No progress found'}), 404
    
    return jsonify({
        'success': True,
        'progress': {
            'chapter_id': progress.chapter_id,
            'current_page': progress.current_page,
            'total_pages': progress.total_pages,
            'percentage': progress.percentage,
            'last_read': progress.last_read.isoformat() if progress.last_read else None
        }
    })


# ============================
# Chapter Navigation API Endpoints
# ============================

@main.route('/api/comics/<int:comic_id>/chapters')
def get_comic_chapters(comic_id):
    """Get all chapters for a comic"""
    chapters = Chapter.query.filter_by(comic_id=comic_id).order_by(Chapter.number).all()
    
    return jsonify({
        'success': True,
        'chapters': [{
            'id': c.id,
            'number': c.number,
            'title': c.title
        } for c in chapters]
    })


@main.route('/api/chapters/<int:chapter_id>/next')
def get_next_chapter(chapter_id):
    """Get the next chapter"""
    chapter = Chapter.query.get_or_404(chapter_id)
    next_chapter = Chapter.query.filter(
        Chapter.comic_id == chapter.comic_id,
        Chapter.number > chapter.number
    ).order_by(Chapter.number).first()
    
    return jsonify({
        'chapter': {
            'id': next_chapter.id,
            'number': next_chapter.number,
            'title': next_chapter.title
        } if next_chapter else None
    })


@main.route('/api/chapters/<int:chapter_id>/prev')
def get_prev_chapter(chapter_id):
    """Get the previous chapter"""
    chapter = Chapter.query.get_or_404(chapter_id)
    prev_chapter = Chapter.query.filter(
        Chapter.comic_id == chapter.comic_id,
        Chapter.number < chapter.number
    ).order_by(Chapter.number.desc()).first()
    
    return jsonify({
        'chapter': {
            'id': prev_chapter.id,
            'number': prev_chapter.number,
            'title': prev_chapter.title
        } if prev_chapter else None
    })


# ============================
# Social Features API Routes
# ============================


# ============================
# Social Features API Routes
# ============================


@main.route('/api/comics/<int:comic_id>/comments', methods=['POST'])
@login_required
@limiter.limit("20 per minute")
def create_comment(comic_id):
    """Create a new comment on a comic"""
    data = request.get_json()
    
    if not data or not data.get('content'):
        return jsonify({'success': False, 'message': 'Content is required'}), 400
    
    from security_utils import sanitize_plain_text
    clean_content = sanitize_plain_text(data.get('content'), max_length=1000)
    if not clean_content:
        return jsonify({'success': False, 'message': 'Valid content is required'}), 400
    
    # Validate comic exists
    comic = Comic.query.get_or_404(comic_id)
    
    comment = Comment(
        user_id=current_user.id,
        comic_id=comic_id,
        content=clean_content,
        chapter_id=data.get('chapter_id'),
        parent_id=data.get('parent_id'),
        is_spoiler=data.get('is_spoiler', False)
    )
    
    db.session.add(comment)
    
    # Create activity for top-level comments
    if not comment.parent_id:
        activity = Activity(
            user_id=current_user.id,
            activity_type='comment',
            comic_id=comic_id,
            chapter_id=comment.chapter_id
        )
        db.session.add(activity)
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'comment': comment.to_dict()
    }), 201


@main.route('/api/comments/<int:comment_id>', methods=['PUT'])
@login_required
@limiter.limit("20 per minute")
def update_comment(comment_id):
    """Update a comment"""
    comment = Comment.query.get_or_404(comment_id)
    
    if comment.user_id != current_user.id:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    data = request.get_json()
    if data and data.get('content'):
        from security_utils import sanitize_plain_text
        clean_content = sanitize_plain_text(data['content'], max_length=1000)
        if not clean_content:
            return jsonify({'success': False, 'message': 'Valid content is required'}), 400
        comment.content = clean_content
    if data and 'is_spoiler' in data:
        comment.is_spoiler = data['is_spoiler']
    
    comment.updated_at = datetime.utcnow()
    db.session.commit()
    
    return jsonify({
        'success': True,
        'comment': comment.to_dict()
    })


@main.route('/api/comments/<int:comment_id>', methods=['DELETE'])
@login_required
def delete_comment(comment_id):
    """Delete a comment"""
    comment = Comment.query.get_or_404(comment_id)
    
    if comment.user_id != current_user.id and not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    db.session.delete(comment)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Comment deleted'
    })


@main.route('/api/comments/<int:comment_id>/like', methods=['POST'])
@login_required
def like_comment(comment_id):
    """Like/unlike a comment"""
    comment = Comment.query.get_or_404(comment_id)
    
    existing_like = CommentLike.query.filter_by(
        user_id=current_user.id,
        comment_id=comment_id
    ).first()
    
    if existing_like:
        db.session.delete(existing_like)
        liked = False
    else:
        like = CommentLike(user_id=current_user.id, comment_id=comment_id)
        db.session.add(like)
        liked = True
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'liked': liked,
        'likes_count': comment.likes_count
    })


# --- Reading Lists ---

@main.route('/api/reading-lists')
@login_required
def get_user_reading_lists():
    """Get user's reading lists"""
    lists = ReadingList.query.filter_by(user_id=current_user.id).order_by(ReadingList.created_at.desc()).all()
    
    return jsonify({
        'success': True,
        'reading_lists': [lst.to_dict() for lst in lists]
    })


@main.route('/api/reading-lists', methods=['POST'])
@login_required
@limiter.limit("30 per minute")
def create_reading_list():
    """Create a new reading list"""
    data = request.get_json()
    
    if not data or not data.get('title'):
        return jsonify({'success': False, 'message': 'Title is required'}), 400
    
    from security_utils import sanitize_plain_text
    clean_title = sanitize_plain_text(data.get('title'), max_length=100)
    if not clean_title:
        return jsonify({'success': False, 'message': 'Valid title is required'}), 400
    
    clean_desc = sanitize_plain_text(data.get('description', ''), max_length=500)
    
    reading_list = ReadingList(
        user_id=current_user.id,
        title=clean_title,
        description=clean_desc,
        is_public=data.get('is_public', True)
    )
    
    db.session.add(reading_list)
    
    # Create activity
    activity = Activity(
        user_id=current_user.id,
        activity_type='list_create',
        reading_list_id=reading_list.id
    )
    db.session.add(activity)
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'reading_list': reading_list.to_dict()
    }), 201


@main.route('/api/reading-lists/<int:list_id>')
def get_reading_list(list_id):
    """Get a reading list with its items"""
    reading_list = ReadingList.query.get_or_404(list_id)
    
    if not reading_list.is_public and (not current_user.is_authenticated or reading_list.user_id != current_user.id):
        return jsonify({'success': False, 'message': 'Not found'}), 404
    
    return jsonify({
        'success': True,
        'reading_list': reading_list.to_dict(include_items=True)
    })


@main.route('/api/reading-lists/<int:list_id>', methods=['PUT'])
@login_required
def update_reading_list(list_id):
    """Update a reading list"""
    reading_list = ReadingList.query.get_or_404(list_id)
    
    if reading_list.user_id != current_user.id:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    data = request.get_json()
    if data.get('name'):
        reading_list.name = data['name'][:100]
    elif data.get('title'):
        reading_list.name = data['title'][:100]
    if 'description' in data:
        reading_list.description = data['description'][:500]
    if 'is_public' in data:
        reading_list.is_public = data['is_public']
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'reading_list': reading_list.to_dict()
    })


@main.route('/api/reading-lists/<int:list_id>', methods=['DELETE'])
@login_required
def delete_reading_list(list_id):
    """Delete a reading list"""
    reading_list = ReadingList.query.get_or_404(list_id)
    
    if reading_list.user_id != current_user.id:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    db.session.delete(reading_list)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Reading list deleted'
    })


@main.route('/api/reading-lists/<int:list_id>/items', methods=['POST'])
@login_required
def add_to_reading_list(list_id):
    """Add a comic to a reading list"""
    reading_list = ReadingList.query.get_or_404(list_id)
    
    if reading_list.user_id != current_user.id:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    data = request.get_json()
    comic_id = data.get('comic_id')
    
    if not comic_id:
        return jsonify({'success': False, 'message': 'Comic ID is required'}), 400
    
    comic = Comic.query.get_or_404(comic_id)
    
    # Check if already in list
    existing = ReadingListItem.query.filter_by(
        reading_list_id=list_id,
        comic_id=comic_id
    ).first()
    
    if existing:
        return jsonify({'success': False, 'message': 'Comic already in list'}), 409
    
    # Get max order
    max_order = db.session.query(db.func.max(ReadingListItem.order)).filter_by(reading_list_id=list_id).scalar() or 0
    
    item = ReadingListItem(
        reading_list_id=list_id,
        comic_id=comic_id,
        order=max_order + 1
    )
    
    db.session.add(item)
    
    # Create activity
    activity = Activity(
        user_id=current_user.id,
        activity_type='add_to_list',
        comic_id=comic_id,
        reading_list_id=list_id
    )
    db.session.add(activity)
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'item': item.to_dict()
    }), 201


@main.route('/api/reading-lists/<int:list_id>/items/<int:item_id>', methods=['DELETE'])
@login_required
def remove_from_reading_list(list_id, item_id):
    """Remove a comic from a reading list"""
    reading_list = ReadingList.query.get_or_404(list_id)
    
    if reading_list.user_id != current_user.id:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    item = ReadingListItem.query.filter_by(
        id=item_id,
        reading_list_id=list_id
    ).first_or_404()
    
    db.session.delete(item)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Removed from reading list'
    })


@main.route('/api/reading-lists/<int:list_id>/remove-comic/<int:comic_id>', methods=['DELETE'])
@login_required
def remove_comic_from_reading_list(list_id, comic_id):
    """Remove a comic from a reading list using comic_id"""
    reading_list = ReadingList.query.get_or_404(list_id)
    
    if reading_list.user_id != current_user.id:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    item = ReadingListItem.query.filter_by(
        comic_id=comic_id,
        reading_list_id=list_id
    ).first()
    
    if not item:
        return jsonify({'success': False, 'message': 'Item not found'}), 404
    
    db.session.delete(item)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Removed from reading list'
    })


@main.route('/reading-list/<int:list_id>')
@login_required
def view_reading_list(list_id):
    """View a reading list with its comics"""
    reading_list = ReadingList.query.get_or_404(list_id)
    
    # Check access
    if reading_list.user_id != current_user.id and not reading_list.is_public:
        abort(403)
    
    items = ReadingListItem.query.filter_by(reading_list_id=list_id).join(
        Comic
    ).order_by(ReadingListItem.added_at.desc()).all()
    
    comics = [item.comic for item in items]
    
    return render_template(
        'user/reading_list_detail.html',
        reading_list=reading_list,
        comics=comics,
        title=reading_list.name
    )


# --- Comment System ---

@main.route('/api/comics/<int:comic_id>/comments')
def get_comic_comments(comic_id):
    """Get comments for a comic"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    # Get top-level comments only
    comments = Comment.query.filter_by(
        comic_id=comic_id,
        parent_id=None
    ).order_by(Comment.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    # Get user's liked comment IDs if logged in
    user_liked = set()
    if current_user.is_authenticated:
        liked = CommentLike.query.filter_by(user_id=current_user.id).filter(
            CommentLike.comment_id.in_([c.id for c in comments.items])
        ).all()
        user_liked = {like.comment_id for like in liked}
    
    return jsonify({
        'success': True,
        'comments': [c.to_dict() for c in comments.items],
        'user_liked': list(user_liked),
        'total': comments.total,
        'pages': comments.pages,
        'current_page': page
    })


# ============================
# Error Handlers
# ============================

def log_error_to_json(error):
    """Log crash details to debug.json"""
    import traceback
    import json
    try:
        debug_file_path = os.path.join(current_app.root_path, 'debug.json')
        
        # Build error info dict
        error_info = {
            'timestamp': datetime.utcnow().isoformat(),
            'error_type': type(error).__name__,
            'error_message': str(error),
            'url': request.url,
            'method': request.method,
            'query_params': dict(request.args),
            'user': current_user.username if (current_user and current_user.is_authenticated) else 'Anonymous',
            'traceback': traceback.format_exc()
        }
        
        # Read existing records
        logs = []
        if os.path.exists(debug_file_path):
            try:
                with open(debug_file_path, 'r', encoding='utf-8') as f:
                    logs = json.load(f)
                    if not isinstance(logs, list):
                        logs = []
            except Exception:
                logs = []
                
        # Append new log
        logs.append(error_info)
        
        # Limit to last 50 errors
        logs = logs[-50:]
        
        with open(debug_file_path, 'w', encoding='utf-8') as f:
            json.dump(logs, f, indent=4, ensure_ascii=False)
    except Exception as log_ex:
        print(f"Error logging failed: {log_ex}")

@main.app_errorhandler(404)
def page_not_found(e):
    return render_template('errors/404.html'), 404

@main.app_errorhandler(Exception)
def handle_exception(e):
    from werkzeug.exceptions import HTTPException
    # Rollback session to clear any failed transaction states before rendering templates
    try:
        db.session.rollback()
    except Exception:
        pass

    if not isinstance(e, HTTPException) or e.code == 500:
        log_error_to_json(e)
        
    if isinstance(e, HTTPException):
        if e.code == 404:
            return render_template('errors/404.html'), 404
        return render_template('errors/500.html'), e.code
    return render_template('errors/500.html'), 500



@main.route('/api/activity/user', methods=['GET'])
@login_required
def get_user_activity():
    """Get current user's activity feed"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    activity = Activity.query.filter_by(user_id=current_user.id).order_by(
        Activity.created_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        'success': True,
        'activities': [{
            'id': a.id,
            'type': a.activity_type,
            'user_id': a.user_id,
            'username': a.user.username,
            'avatar': a.user.avatar,
            'comic_id': a.comic_id,
            'comic_title': a.comic.title if a.comic else None,
            'description': a.description,
            'created_at': a.created_at.isoformat()
        } for a in activity.items],
        'total': activity.total,
        'pages': activity.pages,
        'current_page': page
    })


@main.route('/api/activity/global', methods=['GET'])
def get_global_activity():
    """Get global public activity feed"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    activity = Activity.query.order_by(
        Activity.created_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        'success': True,
        'activities': [{
            'id': a.id,
            'type': a.activity_type,
            'user_id': a.user_id,
            'username': a.user.username,
            'avatar': a.user.avatar,
            'comic_id': a.comic_id,
            'comic_title': a.comic.title if a.comic else None,
            'description': a.description,
            'created_at': a.created_at.isoformat()
        } for a in activity.items],
        'total': activity.total,
        'pages': activity.pages,
        'current_page': page
    })


# ============================
# User Upload Route
# ============================

@main.route('/upload', methods=['GET', 'POST'])
@login_required
def user_upload():
    """User upload page for submitting comics"""
    if request.method == 'POST':
        # Handle file upload
        if 'file' not in request.files:
            flash('No file selected', 'error')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(request.url)
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            upload_folder = current_app.config.get('UPLOAD_FOLDER', 'static/uploads')
            user_upload_dir = os.path.join(upload_folder, 'user_submissions')
            os.makedirs(user_upload_dir, exist_ok=True)
            
            unique_filename = f"{uuid.uuid4().hex}_{filename}"
            filepath = os.path.join(user_upload_dir, unique_filename)
            file.save(filepath)
            
            flash('File uploaded successfully! It will be reviewed by an admin.', 'success')
            return redirect(url_for('main.user_upload'))
        else:
            flash('Invalid file type. Allowed: png, jpg, jpeg, gif, webp, pdf', 'error')
            return redirect(request.url)
    
    return render_template('user/upload.html')


# ============================
# Error Handlers
# ============================

@main.app_errorhandler(404)
def page_not_found(e):
    return render_template('errors/404.html'), 404

@main.app_errorhandler(500)
def internal_server_error(e):
    return render_template('errors/500.html'), 500
