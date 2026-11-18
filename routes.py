"""
ComicVault - Flask Application Routes
Main application routes and API endpoints
"""

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, send_from_directory, current_app, abort, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from models import utc_isoformat, db, User, Comic, Category, Tag, ComicTag, ReadingProgress, Rating, UserLibrary, Setting, Ad, Chapter, Comment, CommentLike, ReadingList, ReadingListItem, Activity, Follow, ComicPage, Bookmark
from datetime import datetime
import os
import uuid
import shutil
import bleach
import hashlib
from urllib.parse import urlsplit
from network_utils import safe_request, download_remote_file
from upload_utils import read_limited, validate_upload, normalized_cover
from extensions import limiter
from security_utils import is_safe_path, is_safe_redirect_target, sanitize_plain_text

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


def wants_json_response():
    return request.path.startswith('/api/') or request.is_json or request.endpoint in {
        'main.admin_test_catbox', 'main.admin_migrate_to_cloud', 'main.admin_test_llm',
        'main.admin_test_upfiles', 'main.admin_unified_upload', 'main.admin_upload_to_host',
        'main.admin_bulk_upload_file'
    }


def public_comic_filter():
    return db.and_(Comic.visibility == 'public', Comic.is_published.is_(True))


def visible_comic_filter():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return db.true()
        return db.or_(public_comic_filter(), Comic.uploader_id == current_user.id)
    return public_comic_filter()


def validated_link(value):
    if not value:
        return None
    if not isinstance(value, str) or len(value) > 1000 or '\\' in value or any(ord(char) < 33 or ord(char) == 127 for char in value):
        abort(400, description='A valid HTTP(S) link is required')
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError()
        parsed.port
    except ValueError:
        abort(400, description='A valid HTTP(S) link is required')
    return value


def storage_reference(value):
    reference = format_storage_ref(value)
    if reference and reference.startswith(('http://', 'https://')):
        return validated_link(reference)
    if reference and (not secure_filename(reference) or ':' in reference or '\x00' in reference):
        abort(400, description='Invalid storage reference')
    return reference


def validate_visibility(value, pdf_file=None, cover_image=None, download_link=None):
    if value not in ('public', 'private', 'draft'):
        abort(400, description='Invalid visibility')
    if value != 'public' and any(reference and reference.startswith(('http://', 'https://')) for reference in (pdf_file, cover_image, download_link)):
        abort(400, description='Private comics and drafts require local assets. Public cloud URLs cannot be made private.')
    return value


def clean_tags(value):
    if not isinstance(value, str) or len(value) > 2000:
        abort(400, description='Invalid tags')
    tags = list(dict.fromkeys(require_text(tag.strip(), 'tag', 50) for tag in value.split(',') if tag.strip()))
    if len(tags) > 20:
        abort(400, description='At most 20 tags are allowed')
    return tags


def save_cover_upload(file, cloud_enabled=False, userhash=''):
    try:
        data = normalized_cover(read_limited(file), file.filename)
    except ValueError as error:
        abort(400, description=str(error))
    name = f'cover_{uuid.uuid4().hex}.jpg'
    if cloud_enabled:
        url = CatboxService(userhash=userhash).upload_file(data, filename=name)
        if not url:
            abort(502, description='The cover could not be uploaded to cloud storage')
        return url
    folder = current_app.config['COVER_UPLOAD_FOLDER']
    os.makedirs(folder, exist_ok=True)
    from security_utils import safe_join_path
    path = safe_join_path(folder, name)
    if not path:
        abort(400, description='Invalid cover path')
    with open(path, 'xb') as target:
        target.write(data)
    return name


def get_accessible_comic(comic_id):
    comic = db.session.get(Comic, comic_id)
    if not comic or not comic.can_view(current_user):
        abort(404)
    return comic


def require_integer(value, name, minimum=1, maximum=2147483647, optional=False):
    if value is None and optional:
        return None
    if isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 10:
        value = int(value)
    if type(value) is not int or not minimum <= value <= maximum:
        abort(400, description=f'{name} must be an integer between {minimum} and {maximum}')
    return value


def require_boolean(value, name):
    if type(value) is not bool:
        abort(400, description=f'{name} must be a boolean')
    return value


def require_text(value, name, max_length, allow_empty=False):
    if not isinstance(value, str) or len(value) > max_length:
        abort(400, description=f'{name} must be text of at most {max_length} characters')
    text = sanitize_plain_text(value, max_length=max_length)
    if not text and not allow_empty:
        abort(400, description=f'{name} is required')
    return text


def validate_chapter(comic_id, chapter_id):
    chapter_id = require_integer(chapter_id, 'chapter_id', optional=True)
    if chapter_id is not None:
        chapter = db.session.get(Chapter, chapter_id)
        if not chapter or chapter.comic_id != comic_id:
            abort(400, description='The chapter must belong to this comic')
    return chapter_id


def persist_reading_progress(data, page_field):
    """Use one validation and calculation path for both reader APIs."""
    comic_id = require_integer(data.get('comic_id'), 'comic_id')
    get_accessible_comic(comic_id)
    chapter_id = validate_chapter(comic_id, data.get('chapter_id'))
    limit = current_app.config['MAX_COMIC_PAGES']
    page = require_integer(data.get(page_field), page_field, maximum=limit)
    total = require_integer(data.get('total_pages'), 'total_pages', minimum=0, maximum=limit, optional=True)
    time_spent = require_integer(data.get('time_spent', 0), 'time_spent', minimum=0, maximum=86400)
    progress = ReadingProgress.query.filter_by(user_id=current_user.id, comic_id=comic_id, chapter_id=chapter_id).first()
    total = total if total is not None else (progress.total_pages if progress else 0)
    if total and page > total:
        abort(400, description='The current page cannot exceed the total page count')
    if not progress:
        progress = ReadingProgress(user_id=current_user.id, comic_id=comic_id, chapter_id=chapter_id, total_time_spent=0)
        db.session.add(progress)
    progress.update_progress(page, total, time_spent)
    db.session.commit()
    return jsonify(success=True, message='Progress saved')


def serialize_reading_list(reading_list, include_items=False):
    items = [item for item in reading_list.items if item.comic and item.comic.can_view(current_user)]
    data = reading_list.to_dict()
    data['items_count'] = len(items)
    if include_items:
        data['items'] = [item.to_dict() for item in items]
    return data


def get_accessible_comment(comment_id, owner_access=False):
    comment = Comment.query.get_or_404(comment_id)
    get_accessible_comic(comment.comic_id)
    if comment.is_hidden and not (current_user.is_authenticated and (current_user.is_admin or (owner_access and comment.user_id == current_user.id))):
        abort(404)
    return comment


def account_recovery_limit_key():
    email = (request.form.get('email') or '').strip().lower()[:120]
    return hashlib.sha256(email.encode('utf-8')).hexdigest()


@main.before_app_request
def validate_request_access():
    if request.is_json and request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        if request.get_data(cache=True) and not isinstance(request.get_json(silent=True), dict):
            abort(400, description='A JSON object is required')
    if request.path == '/admin' or request.path.startswith('/admin/'):
        if not current_user.is_authenticated:
            return current_app.login_manager.unauthorized()
        if not current_user.is_admin:
            abort(403)
    if request.endpoint != 'static':
        return None
    filename = (request.view_args or {}).get('filename', '')
    if not is_safe_path(current_app.static_folder, os.path.join(current_app.static_folder, filename)):
        abort(404)
    if not filename.startswith('uploads/'):
        return None
    parts = filename.split('/')
    extension = os.path.splitext(filename)[1].lower()
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
    if len(parts) < 3 or extension not in image_extensions | {'.pdf'}:
        abort(404)
    if parts[1] in ('covers', 'pages') and extension not in image_extensions:
        abort(404)
    if parts[1] == 'comics' and extension != '.pdf':
        abort(404)
    if current_user.is_authenticated and current_user.is_admin:
        return None  # Administrators also preview newly staged uploads.
    comics = []
    if len(parts) == 4 and parts[1] == 'pages':
        comic_id = require_integer(parts[2], 'comic_id')
        get_accessible_comic(comic_id)
        return None
    if len(parts) == 3 and parts[1] in ('comics', 'covers'):
        column = Comic.pdf_file if parts[1] == 'comics' else Comic.cover_image
        comics = Comic.query.filter(column == parts[2]).all()
        if parts[1] == 'comics':
            comics.extend(chapter.comic for chapter in Chapter.query.filter_by(pdf_file=parts[2]).all())
    if not any(comic.can_view(current_user) for comic in comics):
        abort(404)


@main.after_app_request
def prevent_private_response_caching(response):
    if request.endpoint == 'static' and (request.view_args or {}).get('filename') == 'js/sw.js':
        response.headers['Service-Worker-Allowed'] = '/'
    if request.endpoint != 'static' or (request.view_args or {}).get('filename', '').startswith('uploads/'):
        response.headers['Cache-Control'] = 'no-store'
        response.vary.add('Cookie')
    return response

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
        identifier = (request.form.get('email') or request.form.get('username') or '').strip()[:120]
        password = request.form.get('password') or ''
        remember = request.form.get('remember', False) == 'on'
        
        # Search by email or username
        user = User.query.filter((db.func.lower(User.email) == identifier.lower()) | (db.func.lower(User.username) == identifier.lower())).first()
        
        if user and user.check_password(password):
            if user.is_admin and password == 'admin123':
                flash('Reset the legacy administrator password with the local create-admin command before signing in.', 'danger')
                return render_template('auth/login.html')
            session.clear()
            login_user(user, remember=remember)
            flash(f'Welcome back, {user.username}!', 'success')
            
            next_page = request.args.get('next')
            if is_safe_redirect_target(next_page):
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
@limiter.limit("5 per hour", key_func=account_recovery_limit_key, methods=['POST'])
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
        if user and not user.is_admin and user.check_security_answer(security_answer):
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
        if not user or user.is_admin or current_sig != data.get('pw_sig'):
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


@main.route('/logout', methods=['POST'])
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
    comics_query = Comic.query.filter(public_comic_filter())
    
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
    tags = Tag.query.join(ComicTag, ComicTag.tag == Tag.name).join(Comic, Comic.id == ComicTag.comic_id).filter(
        public_comic_filter(), Tag.name.ilike(f'%{query[:100]}%')
    ).distinct().limit(10).all()
    
    return jsonify({
        'tags': [{'id': t.id, 'name': t.name} for t in tags]
    })


@main.route('/api/comics/random')
def random_comic():
    """Get a random comic"""
    count = Comic.query.filter(public_comic_filter()).count()
    if count == 0:
        return jsonify({'success': False, 'message': 'No comics available'}), 404
    
    import random
    offset = random.randint(0, count - 1)
    comic = Comic.query.filter(public_comic_filter()).offset(offset).first()
    
    if not comic:
        return jsonify({'success': False, 'message': 'No comics found'}), 404
    
    return jsonify({
        'success': True,
        'comic': {
            'id': comic.id,
            'title': comic.title,
            'cover_image': comic.cover_image,
            'url': url_for('main.comic_detail', comic_id=comic.id)
        }
    })


@main.route('/api/comics/<int:comic_id>/similar')
def similar_comics(comic_id):
    """Get similar published comics by category and shared tag text."""
    comic = get_accessible_comic(comic_id)
    similar = Comic.query.filter(
        Comic.id != comic_id, public_comic_filter(), Comic.category == comic.category
    ).order_by(Comic.average_rating.desc()).limit(6).all()
    if len(similar) < 6:
        tags = [tag.tag for tag in comic.tags]
        if tags:
            similar.extend(Comic.query.filter(
                Comic.id != comic_id, public_comic_filter(),
                Comic.id.notin_([item.id for item in similar]),
                Comic.tags.any(ComicTag.tag.in_(tags))
            ).order_by(Comic.average_rating.desc()).limit(6 - len(similar)).all())
    return jsonify(success=True, comics=[{
        'id': item.id, 'title': item.title, 'cover_image': item.cover_image,
        'cover_url': item.cover_url, 'author': item.author,
        'average_rating': item.average_rating,
        'url': url_for('main.comic_detail', comic_id=item.id)
    } for item in similar])


@main.route('/')
def home():
    """Home page with featured comics and categories"""
    # Get featured comics (highest rated or manually featured)
    featured = Comic.query.filter(
        (public_comic_filter()) & ((Comic.is_featured == True) | (Comic.average_rating >= 4.0))
    ).order_by(Comic.average_rating.desc()).limit(12).all()
    
    # Get recently added
    recent = Comic.query.filter(public_comic_filter()).order_by(
        Comic.created_at.desc()
    ).limit(12).all()
    
    # Get trending (most views)
    trending = Comic.query.filter(public_comic_filter()).order_by(
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
            if comic and comic.can_view(current_user):
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
        public_comic_filter()
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
    
    comics_query = Comic.query.filter(public_comic_filter()).order_by(Comic.view_count.desc())
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
    comics_query = Comic.query.filter(public_comic_filter())
    
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
        .join(Comic, Comic.id == ComicTag.comic_id).filter(public_comic_filter())\
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
    comic = get_accessible_comic(comic_id)
    
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
        public_comic_filter()
    ).limit(6).all()
    
    return render_template('comic/detail.html', comic=comic, user_rating=user_rating, in_library=in_library, related=related, user_progress=user_progress)


@main.route('/read/<int:comic_id>')
def read_comic(comic_id):
    """Read comic online"""
    comic = get_accessible_comic(comic_id)
    
    if not comic.pdf_file and not comic.pages.count():
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
    author_comics = Comic.query.filter(Comic.author == comic.author, Comic.id != comic.id, public_comic_filter()).limit(7).all()
    
    # Get popular tags and categories
    popular_tags_query = db.session.query(ComicTag.tag, db.func.count(ComicTag.comic_id).label('count'))\
        .join(Comic, Comic.id == ComicTag.comic_id).filter(public_comic_filter())\
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
    """Return only accessible, complete page sequences."""
    comic = get_accessible_comic(comic_id)
    records = ComicPage.query.filter_by(comic_id=comic.id).order_by(ComicPage.page_number).all()
    if records:
        return jsonify(success=True, comic_id=comic.id, type='images', pages=[{'url': page.image_url} for page in records], total=len(records))
    if not comic.pdf_file:
        return jsonify(success=False, message='No file available'), 404
    pages_dir = os.path.join(current_app.static_folder, 'uploads', 'pages', str(comic.id))
    marker = os.path.join(pages_dir, '.complete')
    if is_safe_path(os.path.join(current_app.static_folder, 'uploads', 'pages'), marker) and os.path.isfile(marker):
        try:
            with open(marker, encoding='ascii') as handle:
                total = int(handle.read(8))
            names = [f'page_{index + 1:03d}.jpg' for index in range(total)] if 1 <= total <= current_app.config['MAX_COMIC_PAGES'] else []
            if names and all(is_safe_path(pages_dir, os.path.join(pages_dir, name)) and os.path.isfile(os.path.join(pages_dir, name)) for name in names):
                return jsonify(success=True, comic_id=comic.id, type='images', pages=[{'url': f'/static/uploads/pages/{comic.id}/{name}'} for name in names], total=len(names))
        except (ValueError, OSError):
            pass
    cloud_enabled = Setting.get('cloud_storage_enabled') == '1' and comic.visibility == 'public' and comic.is_published
    userhash = Setting.get('catbox_userhash', '')
    uploader = create_uploader_from_config({
        'UPLOAD_FOLDER': current_app.config['COMIC_UPLOAD_FOLDER'],
        'COVERS_FOLDER': current_app.config['COVER_UPLOAD_FOLDER'],
        'CLOUD_STORAGE_ENABLED': cloud_enabled, 'CATBOX_USERHASH': userhash
    })
    if comic.pdf_file.startswith(('http://', 'https://')):
        source_pdf = comic.pdf_file
    else:
        from security_utils import safe_join_path
        source_pdf = safe_join_path(current_app.config['COMIC_UPLOAD_FOLDER'], comic.pdf_file)
        if not source_pdf or not os.path.isfile(source_pdf):
            return jsonify(success=False, message='Comic file not found'), 404
    urls = uploader.extract_pages(source_pdf, str(comic.id), upload_to_catbox=cloud_enabled, catbox_userhash=userhash)
    if not urls:
        return jsonify(success=False, message='The comic pages could not be extracted safely'), 422
    if cloud_enabled:
        for index, url in enumerate(urls):
            db.session.add(ComicPage(comic_id=comic.id, page_number=index + 1, image_url=url))
        db.session.commit()
    return jsonify(success=True, comic_id=comic.id, type='images', pages=[{'url': url} for url in urls], total=len(urls))


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
        UserLibrary.user_id == current_user.id, visible_comic_filter()
    ).order_by(UserLibrary.added_at.desc()).limit(5).all()
    
    return render_template('user/profile.html', user=current_user, stats=stats, recent_comics=recent_comics)


@main.route('/library')
@login_required
def library():
    """User's saved comics library"""
    page = request.args.get('page', 1, type=int)
    
    pagination = db.session.query(Comic).join(UserLibrary).filter(
        UserLibrary.user_id == current_user.id, visible_comic_filter()
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
    """Add or remove an accessible comic from the current user's library."""
    if comic_id is None:
        comic_id = (request.get_json(silent=True) or {}).get('comic_id')
    comic_id = require_integer(comic_id, 'comic_id')
    get_accessible_comic(comic_id)
    item = UserLibrary.query.filter_by(user_id=current_user.id, comic_id=comic_id).first()
    if item:
        db.session.delete(item)
        action = 'removed'
    else:
        db.session.add(UserLibrary(user_id=current_user.id, comic_id=comic_id))
        action = 'added'
    db.session.commit()
    return jsonify(success=True, action=action, in_library=action == 'added', message=f'Comic {action} library')


@main.route('/api/reading_progress', methods=['POST'])
@login_required
def update_reading_progress():
    """Save progress from the legacy reader endpoint."""
    return persist_reading_progress(request.get_json(), page_field='current_page')
@main.route('/api/rate_comic', methods=['POST'])
@login_required
def api_rate_comic():
    """Validate and save a rating for an accessible comic."""
    data = request.get_json()
    comic_id = require_integer(data.get('comic_id'), 'comic_id')
    score = require_integer(data.get('score', data.get('rating')), 'score', maximum=5)
    comic = get_accessible_comic(comic_id)
    rating = Rating.query.filter_by(user_id=current_user.id, comic_id=comic_id).first()
    if rating:
        rating.score = score
    else:
        db.session.add(Rating(user_id=current_user.id, comic_id=comic_id, score=score))
    db.session.flush()
    comic.update_rating()
    return jsonify(success=True, new_average=round(comic.average_rating, 1), total_ratings=comic.ratings.count())


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
                         chart_data_user=chart_data_user,
                         chart_data_category=chart_data_category,
                         chart_data_reading=chart_data_reading,
                         chart_data_rating=chart_data_rating)


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
    """Create validated metadata and publish only assets suitable for its visibility."""
    categories = Category.query.all()
    if request.method == 'POST':
        category_name = 'General'
        category_id = require_integer(request.form.get('category_id') or None, 'category_id', optional=True)
        if category_id:
            category = db.session.get(Category, category_id)
            if not category:
                abort(400, description='Unknown category')
            category_name = category.name
        pdf_file = storage_reference(request.form.get('local_path'))
        cover_image = storage_reference(request.form.get('cover_path'))
        download_link = validated_link(request.form.get('download_link'))
        cover = request.files.get('cover')
        visibility = validate_visibility(request.form.get('visibility', 'public'), pdf_file, None if cover and cover.filename else cover_image, download_link)
        comic = Comic(title=require_text(request.form.get('title'), 'title', 200),
            author=require_text(request.form.get('author', ''), 'author', 100, allow_empty=True),
            artist=require_text(request.form.get('artist', ''), 'artist', 100, allow_empty=True),
            description=require_text(request.form.get('description', ''), 'description', 10000, allow_empty=True),
            category=category_name, language=require_text(request.form.get('language', 'English'), 'language', 50),
            visibility=visibility, is_published=visibility != 'draft', pdf_file=pdf_file,
            cover_image=cover_image, download_link=download_link, uploader_id=current_user.id)
        tags = clean_tags(request.form.get('tags', ''))
        cloud_enabled = Setting.get('cloud_storage_enabled') == '1' and visibility == 'public'
        userhash = Setting.get('catbox_userhash', '')
        if cover and cover.filename:
            comic.cover_image = save_cover_upload(cover, cloud_enabled, userhash)
        db.session.add(comic)
        db.session.flush()
        for tag in tags:
            db.session.add(ComicTag(comic_id=comic.id, tag=tag))
        db.session.commit()
        if comic.pdf_file:
            uploader = create_uploader_from_config({'UPLOAD_FOLDER': current_app.config['COMIC_UPLOAD_FOLDER'],
                'COVERS_FOLDER': current_app.config['COVER_UPLOAD_FOLDER'], 'CLOUD_STORAGE_ENABLED': cloud_enabled, 'CATBOX_USERHASH': userhash})
            urls = uploader.extract_pages(comic.pdf_file, str(comic.id), upload_to_catbox=cloud_enabled, catbox_userhash=userhash)
            if urls and cloud_enabled:
                for index, url in enumerate(urls):
                    db.session.add(ComicPage(comic_id=comic.id, page_number=index + 1, image_url=url))
                db.session.commit()
                if userhash:
                    album = CatboxService(userhash).create_album(comic.title, [comic.pdf_file, comic.cover_image] + urls)
                    if album:
                        comic.album_url = album
                        db.session.commit()
        flash('Comic created successfully.', 'success')
        return redirect(url_for('main.admin_comics'))
    return render_template('admin/admin_add_comic.html', categories=categories)


@main.route('/admin/comics/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def admin_comic_edit(id):
    """Validate edits and keep publication state and tags consistent."""
    comic = Comic.query.get_or_404(id)
    if request.method == 'POST':
        cover = request.files.get('cover')
        download_link = validated_link(request.form.get('download_link'))
        visibility = validate_visibility(request.form.get('visibility', comic.visibility), comic.pdf_file, None if cover and cover.filename else comic.cover_image, download_link)
        comic.title = require_text(request.form.get('title'), 'title', 200)
        comic.author = require_text(request.form.get('author', ''), 'author', 100, allow_empty=True)
        comic.artist = require_text(request.form.get('artist', ''), 'artist', 100, allow_empty=True)
        comic.description = require_text(request.form.get('description', ''), 'description', 10000, allow_empty=True)
        episode = request.form.get('episode')
        comic.episode = str(require_integer(episode, 'episode', minimum=0, maximum=1000000)) if episode else None
        comic.category = require_text(request.form.get('category', comic.category or 'General'), 'category', 50)
        comic.language = require_text(request.form.get('language', 'English'), 'language', 50)
        comic.visibility = visibility
        comic.is_published = visibility != 'draft'
        comic.is_featured = request.form.get('is_featured') in ('1', 'on', 'true')
        comic.download_link = download_link
        tags = clean_tags(request.form.get('tags', ''))
        ComicTag.query.filter_by(comic_id=comic.id).delete()
        for tag in tags:
            db.session.add(ComicTag(comic_id=comic.id, tag=tag))
        if cover and cover.filename:
            cloud = Setting.get('cloud_storage_enabled') == '1' and visibility == 'public'
            comic.cover_image = save_cover_upload(cover, cloud, Setting.get('catbox_userhash', ''))
        db.session.commit()
        flash('Comic updated successfully!', 'success')
        return redirect(url_for('main.admin_comics'))
    return render_template('admin/admin_edit_comic.html', comic=comic, categories=Category.query.all())


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
    
    comic = get_accessible_comic(comic_id)
    page = request.args.get('page', 1, type=int)
    chapters = Chapter.query.filter_by(comic_id=comic_id).order_by(Chapter.chapter_number.asc()).paginate(page=page, per_page=20, error_out=False)
    return render_template('admin/chapters.html', comic=comic, chapters=chapters, selected_comic=comic_id, comics=Comic.query.all())


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
    """Validate account edits before changing identity or administrator access."""
    from security_utils import validate_username, validate_email, validate_password
    user = User.query.get_or_404(id)
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        for value, validator in ((username, validate_username), (email, validate_email)):
            valid, message = validator(value)
            if not valid:
                abort(400, description=message)
        duplicate = User.query.filter(User.id != id, db.or_(db.func.lower(User.username) == username.lower(), db.func.lower(User.email) == email)).first()
        if duplicate:
            abort(400, description='Username or email is already registered')
        is_admin = request.form.get('is_admin') == 'on'
        if user.is_admin and not is_admin and User.query.filter_by(is_admin=True).count() <= 1:
            abort(400, description='The last administrator cannot be demoted')
        if password:
            valid, message = validate_password(password)
            if not valid or (is_admin and password == 'admin123'):
                abort(400, description=message or 'The legacy administrator password is not allowed')
            user.set_password(password)
        user.username, user.email, user.is_admin = username, email, is_admin
        if is_admin:
            user.security_answer_hash = None
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
        if 'catbox_userhash' in data:
            userhash = require_text(data['catbox_userhash'], 'catbox_userhash', 128, allow_empty=True)
            
    service = CatboxService(userhash=userhash)
    success, message = service.test_connection(userhash=userhash)
    return jsonify({'success': success, 'message': message})


@main.route('/admin/migrate_to_cloud', methods=['POST'])
@login_required
def admin_migrate_to_cloud():
    """Migrate public assets, committing references before removing local copies."""
    from security_utils import safe_join_path
    from upload_utils import validate_pdf, validate_image
    service = CatboxService(Setting.get('catbox_userhash', ''))
    ok, message = service.test_connection()
    if not ok:
        return jsonify(success=False, message='Cloud storage could not be reached'), 502
    totals = {'comics': 0, 'covers': 0, 'pdfs': 0, 'pages': 0, 'errors': []}
    for comic in Comic.query.filter(public_comic_filter()).all():
        removals = []
        counts = {'covers': 0, 'pdfs': 0, 'pages': 0}
        try:
            for attribute, folder_key, kind in (
                ('cover_image', 'COVER_UPLOAD_FOLDER', 'covers'),
                ('pdf_file', 'COMIC_UPLOAD_FOLDER', 'pdfs')
            ):
                reference = getattr(comic, attribute)
                if not reference or reference.startswith(('http://', 'https://')):
                    continue
                folder = current_app.config[folder_key]
                path = safe_join_path(folder, reference)
                if not path or not os.path.isfile(path):
                    raise ValueError('Local asset is missing or outside its storage folder')
                with open(path, 'rb') as handle:
                    data = read_limited(handle)
                if kind == 'pdfs':
                    validate_pdf(data)
                    filename = os.path.basename(path)
                else:
                    data = normalized_cover(data, os.path.basename(path))
                    filename = f'comic_{comic.id}_cover.jpg'
                url = service.upload_file(data, filename=filename)
                if not url:
                    raise ValueError('An asset upload failed')
                setattr(comic, attribute, url)
                removals.append((folder, path, attribute, reference))
                counts[kind] += 1
            pages_base = os.path.join(current_app.static_folder, 'uploads', 'pages')
            pages_dir = os.path.join(pages_base, str(comic.id))
            if not is_safe_path(pages_base, pages_dir):
                raise ValueError('Invalid page storage path')
            if os.path.isdir(pages_dir):
                names = sorted(name for name in os.listdir(pages_dir) if name.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')))
                uploaded = []
                for name in names:
                    path = safe_join_path(pages_dir, name)
                    if not path:
                        raise ValueError('Invalid page path')
                    with open(path, 'rb') as handle:
                        data = read_limited(handle)
                    validate_image(data, name)
                    url = service.upload_file(data, filename=f'comic_{comic.id}_{name}')
                    if not url:
                        raise ValueError('A page upload failed')
                    uploaded.append(url)
                    removals.append((pages_dir, path, None, None))
                if uploaded:
                    ComicPage.query.filter_by(comic_id=comic.id).delete()
                    for index, url in enumerate(uploaded):
                        db.session.add(ComicPage(comic_id=comic.id, page_number=index + 1, image_url=url))
                    counts['pages'] = len(uploaded)
            # Keep every local file until the database commit has succeeded.
            db.session.commit()
            totals['comics'] += 1
            for kind, count in counts.items():
                totals[kind] += count
        except Exception:
            db.session.rollback()
            totals['errors'].append(f'Comic #{comic.id}: migration failed; local files were retained.')
            continue
        for folder, path, attribute, reference in removals:
            if attribute and Comic.query.filter(getattr(Comic, attribute) == reference).first():
                continue  # A different comic still uses this local copy.
            if is_safe_path(folder, path):
                try:
                    os.remove(path)
                except OSError:
                    totals['errors'].append(f'Comic #{comic.id}: a local copy could not be removed.')
        if counts['pages']:
            marker = os.path.join(pages_dir, '.complete')
            if is_safe_path(pages_dir, marker):
                try:
                    if os.path.isfile(marker):
                        os.remove(marker)
                    os.rmdir(pages_dir)
                except OSError:
                    pass
    return jsonify(success=not totals['errors'],
        message=f"Processed {totals['comics']} public comics.",
        stats=totals)


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
            
        response = safe_request(
            'POST', url,
            headers=headers,
            json={
                'model': model,
                'messages': [{'role': 'user', 'content': 'Hello'}],
                'max_tokens': 10
            },
            timeout=10,
            allow_local=Setting.get('llm_use_local') == '1',
            require_https=bool(api_key) and Setting.get('llm_use_local') != '1'
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
        
        response = safe_request('POST', endpoint, files=files, timeout=30, require_https=True)
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
        cloud_enabled = Setting.get('cloud_storage_enabled') == '1' and request.form.get('visibility', 'draft') == 'public'
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
        should_upload = bool(uploader.upfiles_api_key) and request.form.get('upload_to_upfiles', 'true').lower() == 'true'
        
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
            status = 400 if result.get('validation_error') else 502
            return jsonify({'success': False, 'message': f"Process failed: {', '.join(result['errors'])}"}), status
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@main.route('/admin/upload_to_host', methods=['POST'])
@login_required
def admin_upload_to_host():
    """Upload a bounded and validated comic to the configured host."""
    data = request.get_json()
    reference = data.get('local_path')
    if not isinstance(reference, str) or not reference:
        abort(400, description='A local comic reference or URL is required')
    uploader = create_uploader_from_config({'UPLOAD_FOLDER': current_app.config['COMIC_UPLOAD_FOLDER'],
        'COVERS_FOLDER': current_app.config['COVER_UPLOAD_FOLDER'],
        'UPFILES_API_KEY': Setting.get('upfiles_token'), 'UPFILES_ENDPOINT': Setting.get('upfiles_endpoint', 'https://api.upfiles.com/upload')})
    known = Comic.query.filter_by(pdf_file=format_storage_ref(reference)).all()
    if data.get('visibility', 'public') != 'public' or (known and not any(comic.visibility == 'public' and comic.is_published for comic in known)):
        abort(400, description='Publish the comic before sending it to a public upload host')
    result = uploader._upload_to_upfiles(reference)
    if result.get('success'):
        return jsonify(success=True, upfiles_url=result.get('url'))
    return jsonify(success=False, message=result.get('message', 'Upload failed')), 400

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
        cloud_enabled = False  # Drafts stay in protected local storage.
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
        should_upload = False  # Public hosting starts only after publication.
        
        # Run AI upload workflow
        result = uploader.upload_comic(
            file_stream=pdf_file,
            filename=pdf_file.filename,
            extract_metadata=True,
            upload_to_upfiles=should_upload
        )
        
        if not result.get('local_path'):
            if result.get('validation_error'):
                return jsonify(success=False, message='A valid PDF within the file limits is required'), 400
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
    """Create a bookmark only for an accessible comic and matching chapter."""
    data = request.get_json()
    comic_id = require_integer(data.get('comic_id'), 'comic_id')
    page_number = require_integer(data.get('page_number'), 'page_number', maximum=current_app.config['MAX_COMIC_PAGES'])
    get_accessible_comic(comic_id)
    chapter_id = validate_chapter(comic_id, data.get('chapter_id'))
    note = require_text(data.get('note', ''), 'note', 255, allow_empty=True)
    existing = Bookmark.query.filter_by(user_id=current_user.id, comic_id=comic_id, chapter_id=chapter_id, page_number=page_number).first()
    if existing:
        return jsonify(success=False, message='Bookmark already exists at this page'), 409
    bookmark = Bookmark(user_id=current_user.id, comic_id=comic_id, chapter_id=chapter_id, page_number=page_number, note=note)
    db.session.add(bookmark)
    db.session.commit()
    return jsonify(success=True, bookmark=bookmark.to_dict())


@main.route('/api/bookics/<int:comic_id>')
@main.route('/api/bookmarks/<int:comic_id>')
@main.route('/api/comics/<int:comic_id>/bookmarks')
@login_required
def get_comic_bookmarks(comic_id):
    """Get the current user's bookmarks for an accessible comic."""
    get_accessible_comic(comic_id)
    bookmarks = Bookmark.query.filter_by(user_id=current_user.id, comic_id=comic_id).order_by(Bookmark.page_number).all()
    return jsonify(success=True, bookmarks=[bookmark.to_dict() for bookmark in bookmarks])


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
    """Save progress from the chapter-aware reader endpoint."""
    return persist_reading_progress(request.get_json(), page_field='page_number')


@main.route('/api/reading-progress/<int:comic_id>')
@login_required
def get_reading_progress(comic_id):
    """Get reading progress for a comic"""
    get_accessible_comic(comic_id)
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
            'last_read': utc_isoformat(progress.last_read) if progress.last_read else None
        }
    })


# ============================
# Chapter Navigation API Endpoints
# ============================

@main.route('/api/comics/<int:comic_id>/chapters')
def get_comic_chapters(comic_id):
    """Get ordered chapters for an accessible comic."""
    get_accessible_comic(comic_id)
    chapters = Chapter.query.filter_by(comic_id=comic_id).order_by(Chapter.chapter_number).all()
    return jsonify(success=True, chapters=[{'id': chapter.id, 'number': chapter.chapter_number, 'title': chapter.title} for chapter in chapters])


@main.route('/api/chapters/<int:chapter_id>/next')
def get_next_chapter(chapter_id):
    """Get the next chapter without exposing private comic metadata."""
    chapter = Chapter.query.get_or_404(chapter_id)
    get_accessible_comic(chapter.comic_id)
    following = Chapter.query.filter(Chapter.comic_id == chapter.comic_id, Chapter.chapter_number > chapter.chapter_number).order_by(Chapter.chapter_number).first()
    return jsonify(chapter={'id': following.id, 'number': following.chapter_number, 'title': following.title} if following else None)


@main.route('/api/chapters/<int:chapter_id>/prev')
def get_prev_chapter(chapter_id):
    """Get the previous chapter without exposing private comic metadata."""
    chapter = Chapter.query.get_or_404(chapter_id)
    get_accessible_comic(chapter.comic_id)
    previous = Chapter.query.filter(Chapter.comic_id == chapter.comic_id, Chapter.chapter_number < chapter.chapter_number).order_by(Chapter.chapter_number.desc()).first()
    return jsonify(chapter={'id': previous.id, 'number': previous.chapter_number, 'title': previous.title} if previous else None)


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
    """Create a comment with validated parent, chapter, and privacy."""
    get_accessible_comic(comic_id)
    data = request.get_json()
    content = require_text(data.get('content'), 'content', 1000)
    chapter_id = validate_chapter(comic_id, data.get('chapter_id'))
    parent_id = require_integer(data.get('parent_id'), 'parent_id', optional=True)
    if parent_id is not None:
        parent = db.session.get(Comment, parent_id)
        if not parent or parent.comic_id != comic_id or parent.is_hidden or (chapter_id is not None and parent.chapter_id != chapter_id):
            abort(400, description='The parent comment must belong to this comic and chapter')
        ancestor, depth = parent, 0
        while ancestor:
            depth += 1
            if depth > 20:
                abort(400, description='The maximum reply depth has been reached')
            ancestor = ancestor.parent
    spoiler = require_boolean(data.get('is_spoiler', False), 'is_spoiler')
    comment = Comment(user_id=current_user.id, comic_id=comic_id, chapter_id=chapter_id, parent_id=parent_id, content=content, is_spoiler=spoiler)
    db.session.add(comment)
    if parent_id is None:
        comic = db.session.get(Comic, comic_id)
        db.session.add(Activity(user_id=current_user.id, activity_type='comment', comic_id=comic_id, chapter_id=chapter_id, is_public=comic.visibility == 'public' and comic.is_published))
    db.session.commit()
    return jsonify(success=True, comment=comment.to_dict()), 201


@main.route('/api/comments/<int:comment_id>', methods=['PUT'])
@login_required
@limiter.limit("20 per minute")
def update_comment(comment_id):
    """Update only the current user's comment."""
    comment = get_accessible_comment(comment_id, owner_access=True)
    if comment.user_id != current_user.id:
        abort(403)
    data = request.get_json()
    if 'content' in data:
        comment.content = require_text(data['content'], 'content', 1000)
    if 'is_spoiler' in data:
        comment.is_spoiler = require_boolean(data['is_spoiler'], 'is_spoiler')
    comment.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(success=True, comment=comment.to_dict())


@main.route('/api/comments/<int:comment_id>', methods=['DELETE'])
@login_required
def delete_comment(comment_id):
    """Delete an owned comment, or moderate it as an administrator."""
    comment = get_accessible_comment(comment_id, owner_access=True)
    if comment.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    db.session.delete(comment)
    db.session.commit()
    return jsonify(success=True, message='Comment deleted')


@main.route('/api/comments/<int:comment_id>/like', methods=['POST'])
@login_required
def like_comment(comment_id):
    """Toggle a like and keep the displayed count consistent."""
    comment = get_accessible_comment(comment_id)
    existing = CommentLike.query.filter_by(user_id=current_user.id, comment_id=comment_id).first()
    if existing:
        db.session.delete(existing)
        liked = False
    else:
        db.session.add(CommentLike(user_id=current_user.id, comment_id=comment_id))
        liked = True
    db.session.flush()
    comment.likes_count = CommentLike.query.filter_by(comment_id=comment_id).count()
    db.session.commit()
    return jsonify(success=True, liked=liked, likes_count=comment.likes_count)


# --- Reading Lists ---

@main.route('/api/reading-lists')
@login_required
def get_user_reading_lists():
    """Get the current user's lists with accessible item counts."""
    lists = ReadingList.query.filter_by(user_id=current_user.id).order_by(ReadingList.created_at.desc()).all()
    return jsonify(success=True, reading_lists=[serialize_reading_list(item) for item in lists])


@main.route('/api/reading-lists', methods=['POST'])
@login_required
@limiter.limit("30 per minute")
def create_reading_list():
    """Create a validated reading list and its linked activity."""
    data = request.get_json()
    title = require_text(data.get('title'), 'title', 100)
    description = require_text(data.get('description', ''), 'description', 500, allow_empty=True)
    is_public = require_boolean(data.get('is_public', True), 'is_public')
    reading_list = ReadingList(user_id=current_user.id, title=title, description=description, is_public=is_public)
    db.session.add(reading_list)
    db.session.flush()
    db.session.add(Activity(user_id=current_user.id, activity_type='list_create', reading_list_id=reading_list.id, is_public=is_public))
    db.session.commit()
    return jsonify(success=True, reading_list=serialize_reading_list(reading_list)), 201


@main.route('/api/reading-lists/<int:list_id>')
def get_reading_list(list_id):
    """Get a public or owned reading list without leaking private comic items."""
    reading_list = ReadingList.query.get_or_404(list_id)
    if not reading_list.is_public and (not current_user.is_authenticated or reading_list.user_id != current_user.id):
        abort(404)
    return jsonify(success=True, reading_list=serialize_reading_list(reading_list, include_items=True))


@main.route('/api/reading-lists/<int:list_id>', methods=['PUT'])
@login_required
def update_reading_list(list_id):
    """Persist sanitized edits to the mapped title field."""
    reading_list = ReadingList.query.get_or_404(list_id)
    if reading_list.user_id != current_user.id:
        abort(403)
    data = request.get_json()
    if 'title' in data or 'name' in data:
        reading_list.title = require_text(data.get('title', data.get('name')), 'title', 100)
    if 'description' in data:
        reading_list.description = require_text(data['description'], 'description', 500, allow_empty=True)
    if 'is_public' in data:
        reading_list.is_public = require_boolean(data['is_public'], 'is_public')
    db.session.commit()
    return jsonify(success=True, reading_list=serialize_reading_list(reading_list))


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
    comic_id = require_integer(data.get('comic_id'), 'comic_id')
    comic = get_accessible_comic(comic_id)
    
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
        reading_list_id=list_id,
        is_public=reading_list.is_public and comic.visibility == 'public' and comic.is_published
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
def view_reading_list(list_id):
    """Render an owned or public collection with only accessible comics."""
    reading_list = ReadingList.query.get_or_404(list_id)
    if not reading_list.is_public and (not current_user.is_authenticated or reading_list.user_id != current_user.id):
        abort(404)
    items = ReadingListItem.query.filter_by(reading_list_id=list_id).order_by(ReadingListItem.order, ReadingListItem.added_at).all()
    comics = [item.comic for item in items if item.comic and item.comic.can_view(current_user)]
    return render_template('user/reading_list_detail.html', reading_list=reading_list, comics=comics, title=reading_list.title)


# --- Comment System ---

@main.route('/api/comics/<int:comic_id>/comments')
def get_comic_comments(comic_id):
    """Get visible top-level comments with bounded pagination."""
    get_accessible_comic(comic_id)
    page = max(1, request.args.get('page', 1, type=int))
    per_page = max(1, min(100, request.args.get('per_page', 20, type=int)))
    comments = Comment.query.filter_by(comic_id=comic_id, parent_id=None, is_hidden=False).order_by(Comment.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    liked = []
    if current_user.is_authenticated:
        liked = [item.comment_id for item in CommentLike.query.filter_by(user_id=current_user.id).filter(CommentLike.comment_id.in_([comment.id for comment in comments.items])).all()]
    return jsonify(success=True, comments=[comment.to_dict() for comment in comments.items], user_liked=liked, total=comments.total, pages=comments.pages, current_page=page)


@main.route('/api/comments/<int:comment_id>/replies')
def get_comment_replies(comment_id):
    """Return the visible replies requested by the comment widget."""
    parent = get_accessible_comment(comment_id)
    page = max(1, request.args.get('page', 1, type=int))
    replies = Comment.query.filter_by(parent_id=parent.id, is_hidden=False).order_by(Comment.created_at).paginate(page=page, per_page=100, error_out=False)
    return jsonify(success=True, replies=[reply.to_dict() for reply in replies.items], total=replies.total, pages=replies.pages)


# ============================
# Error Handlers
# ============================

def log_error(error):
    """Log useful stack locations without passwords, reset tokens, or SQL values."""
    import traceback
    stack = ''.join(traceback.format_list(traceback.extract_tb(error.__traceback__)))
    current_app.logger.error('Unhandled %s for %s %s\n%s', type(error).__name__, request.method, request.path, stack)

@main.app_errorhandler(404)
def page_not_found(e):
    if wants_json_response():
        return jsonify(success=False, message='Not found'), 404
    return render_template('errors/404.html'), 404

@main.app_errorhandler(Exception)
def handle_exception(error):
    from werkzeug.exceptions import HTTPException
    db.session.rollback()
    if isinstance(error, HTTPException):
        response = error.get_response()
        if wants_json_response():
            response.data = current_app.json.dumps({'success': False, 'message': error.description, 'error': error.name})
            response.content_type = 'application/json'
        else:
            response.data = render_template('errors/http.html', error=error)
        return response
    log_error(error)
    if wants_json_response():
        return jsonify(success=False, message='Internal server error'), 500
    return render_template('errors/500.html'), 500



@main.route('/api/activity/user', methods=['GET'])
@login_required
def get_user_activity():
    """Get the current user's activity feed."""
    page = max(1, request.args.get('page', 1, type=int))
    per_page = max(1, min(100, request.args.get('per_page', 20, type=int)))
    activity = Activity.query.filter(Activity.user_id == current_user.id,
        db.or_(Activity.comic_id.is_(None), Activity.comic.has(visible_comic_filter())),
        db.or_(Activity.chapter_id.is_(None), Activity.chapter.has(Chapter.comic.has(visible_comic_filter())))
    ).order_by(Activity.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return jsonify(success=True, activities=[serialize_activity(item) for item in activity.items], total=activity.total, pages=activity.pages, current_page=page)


@main.route('/api/activity/global', methods=['GET'])
def get_global_activity():
    """Get public activity whose associated comics and lists remain public."""
    page = max(1, request.args.get('page', 1, type=int))
    per_page = max(1, min(100, request.args.get('per_page', 20, type=int)))
    activity = Activity.query.filter(
        Activity.is_public.is_(True),
        db.or_(Activity.comic_id.is_(None), Activity.comic.has(public_comic_filter())),
        db.or_(Activity.reading_list_id.is_(None), Activity.reading_list.has(ReadingList.is_public.is_(True))),
        db.or_(Activity.chapter_id.is_(None), Activity.chapter.has(Chapter.comic.has(public_comic_filter())))
    ).order_by(Activity.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return jsonify(success=True, activities=[serialize_activity(item) for item in activity.items], total=activity.total, pages=activity.pages, current_page=page)


def serialize_activity(activity):
    data = activity.to_dict()
    data.update(type=activity.activity_type, username=activity.user.username, avatar=activity.user.avatar,
                comic_id=activity.comic_id, comic_title=activity.comic.title if activity.comic else None,
                description=activity.description)
    return data


# ============================
# User Upload Route
# ============================

@main.route('/upload', methods=['GET', 'POST'])
@login_required
@limiter.limit('20 per hour', methods=['POST'], key_func=lambda: str(current_user.id) if current_user.is_authenticated else (request.remote_addr or 'unknown'))
def user_upload():
    """Store validated submissions in an administrator-only review directory."""
    if request.method == 'POST':
        file = request.files.get('file')
        if not file or not file.filename:
            flash('No file selected', 'error')
            return redirect(url_for('main.user_upload'))
        try:
            data = validate_upload(read_limited(file), file.filename)
        except ValueError as error:
            abort(400, description=str(error))
        directory = os.path.join(current_app.config['UPLOAD_FOLDER'], 'user_submissions')
        os.makedirs(directory, exist_ok=True)
        prefix = f'{current_user.id}_'
        current_size = sum(os.path.getsize(os.path.join(directory, name)) for name in os.listdir(directory)
                           if name.startswith(prefix) and is_safe_path(directory, os.path.join(directory, name)) and os.path.isfile(os.path.join(directory, name)))
        if current_size + len(data) > 100 * 1024 * 1024:
            abort(413, description='The pending submission quota has been reached')
        from security_utils import safe_join_path
        name = f'{prefix}{uuid.uuid4().hex}_{secure_filename(file.filename)}'
        path = safe_join_path(directory, name)
        if not path:
            abort(400, description='Invalid filename')
        with open(path, 'xb') as target:
            target.write(data)
        flash('File uploaded successfully! It will be reviewed by an admin.', 'success')
        return redirect(url_for('main.user_upload'))
    return render_template('user/upload.html')


# ============================
# Error Handlers
# ============================

@main.app_errorhandler(404)
def page_not_found(e):
    if wants_json_response():
        return jsonify(success=False, message='Not found'), 404
    return render_template('errors/404.html'), 404

@main.app_errorhandler(500)
def internal_server_error(e):
    return render_template('errors/500.html'), 500
