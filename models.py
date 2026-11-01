from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(UserMixin, db.Model):
    """User model for authentication and profiles"""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256))
    security_answer_hash = db.Column(db.String(256))
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    reading_progress = db.relationship('ReadingProgress', backref='user', lazy='dynamic')
    ratings = db.relationship('Rating', backref='user', lazy='dynamic')
    
    def set_password(self, password):
        """Hash and set user password"""
        self.password_hash = generate_password_hash(password, method='scrypt')
    
    def check_password(self, password):
        """Check password against hash"""
        return check_password_hash(self.password_hash, password)
    
    def set_security_answer(self, answer):
        """Normalize and hash security answer using scrypt"""
        if answer:
            norm_answer = " ".join(str(answer).strip().lower().split())
            self.security_answer_hash = generate_password_hash(norm_answer, method='scrypt')
        else:
            self.security_answer_hash = None
            
    def check_security_answer(self, answer):
        """Verify security answer against scrypt hash"""
        if not self.security_answer_hash or not answer:
            return False
        norm_answer = " ".join(str(answer).strip().lower().split())
        return check_password_hash(self.security_answer_hash, norm_answer)
    
    @property
    def avatar(self):
        """Default user avatar path"""
        return 'default-avatar.png'
    
    def __repr__(self):
        return f'<User {self.username}>'

class Category(db.Model):
    """Category model for organizing comics"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    slug = db.Column(db.String(50), unique=True, nullable=False)
    icon = db.Column(db.String(100), default='fas fa-book')
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Category {self.name}>'


class Tag(db.Model):
    """Tag model for comic tags"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Tag {self.name}>'


class ComicTag(db.Model):
    """Association table for comic tags"""
    id = db.Column(db.Integer, primary_key=True)
    comic_id = db.Column(db.Integer, db.ForeignKey('comic.id'), nullable=False)
    tag = db.Column(db.String(50), nullable=False)



class Comic(db.Model):
    """Comic model for storing comic metadata"""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    episode = db.Column(db.String(100))
    author = db.Column(db.String(100))
    artist = db.Column(db.String(100))
    description = db.Column(db.Text)
    cover_image = db.Column(db.String(500))
    pdf_file = db.Column(db.String(500))
    album_url = db.Column(db.String(500))  # Catbox.moe Album URL (e.g. https://catbox.moe/c/xxxxxx)
    download_link = db.Column(db.String(1000))  # External download URL from upload host
    category = db.Column(db.String(50), default='General')
    language = db.Column(db.String(50), default='English')
    is_published = db.Column(db.Boolean, default=True)
    is_featured = db.Column(db.Boolean, default=False)
    visibility = db.Column(db.String(20), default='public')  # public, private, draft
    view_count = db.Column(db.Integer, default=0)
    average_rating = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    uploader_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    
    # Relationships
    tags = db.relationship('ComicTag', backref='comic', lazy='dynamic', cascade='all, delete-orphan')
    chapters = db.relationship('Chapter', backref='comic', lazy='dynamic', cascade='all, delete-orphan')
    pages = db.relationship('ComicPage', backref='comic', lazy='dynamic', cascade='all, delete-orphan', order_by='ComicPage.page_number')
    ratings = db.relationship('Rating', backref='comic', lazy='dynamic', cascade='all, delete-orphan')
    reading_progress = db.relationship('ReadingProgress', backref='comic', lazy='dynamic', cascade='all, delete-orphan')
    
    @property
    def cover_url(self):
        """Return the URL for the cover image"""
        if self.cover_image:
            if self.cover_image.startswith(('http://', 'https://')):
                return self.cover_image
            return f'/static/uploads/covers/{self.cover_image}'
        # Return a high-quality placeholder if no cover exists
        return 'https://via.placeholder.com/300x450.png?text=No+Cover'

    @property
    def pdf_url(self):
        """Return the URL for the comic PDF (cloud URL or local static URL)"""
        if not self.pdf_file:
            return None
        if self.pdf_file.startswith(('http://', 'https://')):
            return self.pdf_file
        return f'/static/uploads/comics/{self.pdf_file}'

    def __repr__(self):
        return f'<Comic {self.title}>'
    
    def update_rating(self):
        """Update average rating"""
        ratings = [r.score for r in self.ratings]
        self.average_rating = sum(ratings) / len(ratings) if ratings else 0.0
        db.session.commit()
    
    def to_dict(self):
        """Convert comic to dictionary"""
        return {
            'id': self.id,
            'title': self.title,
            'author': self.author,
            'artist': self.artist,
            'description': self.description,
            'cover_image': self.cover_image,
            'cover_url': self.cover_url,
            'pdf_file': self.pdf_file,
            'album_url': self.album_url,
            'download_link': self.download_link,
            'category': self.category,
            'language': self.language,
            'tags': [t.tag for t in self.tags],
            'is_published': self.is_published,
            'is_featured': self.is_featured,
            'visibility': self.visibility,
            'average_rating': self.average_rating,
            'view_count': self.view_count,
            'created_at': self.created_at.isoformat()
        }


class Chapter(db.Model):
    """Chapter model for comic chapters"""
    id = db.Column(db.Integer, primary_key=True)
    comic_id = db.Column(db.Integer, db.ForeignKey('comic.id'), nullable=False)
    chapter_number = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(200))
    pdf_file = db.Column(db.String(500))
    page_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Chapter {self.chapter_number}: {self.title}>'


class ComicPage(db.Model):
    """Model for tracking comic pages (both local paths and cloud URLs)"""
    __tablename__ = 'comic_page'
    
    id = db.Column(db.Integer, primary_key=True)
    comic_id = db.Column(db.Integer, db.ForeignKey('comic.id'), nullable=False)
    chapter_id = db.Column(db.Integer, db.ForeignKey('chapter.id'), nullable=True)
    page_number = db.Column(db.Integer, nullable=False)
    image_url = db.Column(db.String(1000), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'page_number': self.page_number,
            'url': self.image_url
        }

    def __repr__(self):
        return f'<ComicPage {self.comic_id} - Page {self.page_number}>'





class Rating(db.Model):
    """Rating model for user comic ratings"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    comic_id = db.Column(db.Integer, db.ForeignKey('comic.id'), nullable=False)
    score = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Rating {self.score} for Comic {self.comic_id}>'


class Ad(db.Model):
    """Advertisement model for managing ads"""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False, default='')
    ad_code = db.Column(db.Text, nullable=False, default='')
    banner_link = db.Column(db.String(500))
    target_url = db.Column(db.String(500))
    placement = db.Column(db.String(50), default='sidebar')  # header, sidebar, footer, comic-detail
    ad_type = db.Column(db.String(20), default='banner')  # banner, popup, etc.
    is_active = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Ad {self.title}>'


class Setting(db.Model):
    """Settings model for storing application configuration"""
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)
    description = db.Column(db.String(500))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Setting {self.key}>'
    
    def get_decrypted_value(self):
        """Return the decrypted plaintext value if sensitive/encrypted"""
        from crypto_utils import decrypt_val, is_sensitive_key
        if is_sensitive_key(self.key) or (self.value and str(self.value).startswith('enc:')):
            return decrypt_val(self.value)
        return self.value

    @staticmethod
    def get(key, default=None):
        """Get a setting value by key, automatically decrypting sensitive credentials"""
        from crypto_utils import decrypt_val, is_sensitive_key
        setting = Setting.query.filter_by(key=key).first()
        if not setting or setting.value is None:
            return default
        if is_sensitive_key(key) or str(setting.value).startswith('enc:'):
            return decrypt_val(setting.value)
        return setting.value
    
    @staticmethod
    def set(key, value, description=None):
        """Set a setting value, automatically encrypting sensitive credentials at rest"""
        from crypto_utils import encrypt_val, is_sensitive_key
        stored_value = encrypt_val(value) if (value and is_sensitive_key(key)) else value
        
        setting = Setting.query.filter_by(key=key).first()
        if setting:
            setting.value = stored_value
            if description:
                setting.description = description
        else:
            setting = Setting(key=key, value=stored_value, description=description)
            db.session.add(setting)
        db.session.commit()
        return setting

    @staticmethod
    def get_all_dict():
        """Return all settings as a dictionary with sensitive values decrypted for display"""
        return {s.key: s.get_decrypted_value() for s in Setting.query.all()}


class UserLibrary(db.Model):
    """User library model for storing user's saved comics"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    comic_id = db.Column(db.Integer, db.ForeignKey('comic.id'), nullable=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', backref=db.backref('library_items', lazy=True))
    comic = db.relationship('Comic', backref=db.backref('library_users', lazy=True, cascade='all, delete-orphan'))
    
    def __repr__(self):
        return f'<UserLibrary user={self.user_id} comic={self.comic_id}>'


# Phase 3: Social Features Models

class Comment(db.Model):
    """Comment model for comic and chapter discussions"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    comic_id = db.Column(db.Integer, db.ForeignKey('comic.id'), nullable=False)
    chapter_id = db.Column(db.Integer, db.ForeignKey('chapter.id'), nullable=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('comment.id'), nullable=True)
    content = db.Column(db.Text, nullable=False)
    is_spoiler = db.Column(db.Boolean, default=False)
    is_hidden = db.Column(db.Boolean, default=False)
    is_reported = db.Column(db.Boolean, default=False)
    report_reason = db.Column(db.String(500))
    likes_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', backref=db.backref('comments', lazy=True))
    comic = db.relationship('Comic', backref=db.backref('comments', lazy=True, cascade='all, delete-orphan'))
    chapter = db.relationship('Chapter', backref=db.backref('comments', lazy=True))
    parent = db.relationship('Comment', remote_side=[id], backref=db.backref('replies', lazy=True))
    likes = db.relationship('CommentLike', backref='comment', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Comment {self.id} by {self.user_id} on comic {self.comic_id}>'
    
    def to_dict(self):
        """Convert comment to dictionary"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'user': {
                'id': self.user.id,
                'username': self.user.username,
                'avatar': self.user.avatar
            },
            'content': self.content,
            'is_spoiler': self.is_spoiler,
            'is_hidden': self.is_hidden,
            'likes_count': self.likes_count,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'replies_count': len(self.replies) if self.replies else 0
        }


class CommentLike(db.Model):
    """Comment like model for tracking user likes on comments"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    comment_id = db.Column(db.Integer, db.ForeignKey('comment.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Unique constraint to prevent duplicate likes
    __table_args__ = (db.UniqueConstraint('user_id', 'comment_id', name='unique_comment_like'),)
    
    def __repr__(self):
        return f'<CommentLike user={self.user_id} comment={self.comment_id}>'


class ReadingList(db.Model):
    """Reading list model for user-created comic collections"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    is_public = db.Column(db.Boolean, default=True)
    is_staff_pick = db.Column(db.Boolean, default=False)
    likes_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', backref=db.backref('reading_lists', lazy=True))
    items = db.relationship('ReadingListItem', backref='reading_list', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<ReadingList {self.title} by {self.user_id}>'
    
    def to_dict(self, include_items=False):
        """Convert reading list to dictionary"""
        data = {
            'id': self.id,
            'user_id': self.user_id,
            'user': {
                'id': self.user.id,
                'username': self.user.username,
                'avatar': self.user.avatar
            },
            'title': self.title,
            'description': self.description,
            'is_public': self.is_public,
            'is_staff_pick': self.is_staff_pick,
            'likes_count': self.likes_count,
            'items_count': len(self.items) if self.items else 0,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }
        if include_items:
            data['items'] = [item.to_dict() for item in self.items]
        return data


class ReadingListItem(db.Model):
    """Reading list item model for comics in a reading list"""
    id = db.Column(db.Integer, primary_key=True)
    reading_list_id = db.Column(db.Integer, db.ForeignKey('reading_list.id'), nullable=False)
    comic_id = db.Column(db.Integer, db.ForeignKey('comic.id'), nullable=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    order = db.Column(db.Integer, default=0)
    
    # Relationships
    comic = db.relationship('Comic', backref=db.backref('reading_list_items', lazy=True, cascade='all, delete-orphan'))
    
    # Unique constraint to prevent duplicate comics in same list
    __table_args__ = (db.UniqueConstraint('reading_list_id', 'comic_id', name='unique_reading_list_item'),)
    
    def __repr__(self):
        return f'<ReadingListItem list={self.reading_list_id} comic={self.comic_id}>'
    
    def to_dict(self):
        """Convert reading list item to dictionary"""
        return {
            'id': self.id,
            'comic_id': self.comic_id,
            'comic': {
                'id': self.comic.id,
                'title': self.comic.title,
                'cover_image': self.comic.cover_image,
                'author': self.comic.author,
                'average_rating': self.comic.average_rating
            },
            'added_at': self.added_at.isoformat(),
            'order': self.order
        }


class Activity(db.Model):
    """Activity model for tracking user actions and feeds"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    activity_type = db.Column(db.String(50), nullable=False)  # 'read', 'favorite', 'rating', 'comment', 'follow', 'list_create'
    comic_id = db.Column(db.Integer, db.ForeignKey('comic.id'), nullable=True)
    chapter_id = db.Column(db.Integer, db.ForeignKey('chapter.id'), nullable=True)
    target_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    reading_list_id = db.Column(db.Integer, db.ForeignKey('reading_list.id'), nullable=True)
    data = db.Column(db.JSON)  # Additional activity data
    is_public = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('activities', lazy=True))
    target_user = db.relationship('User', foreign_keys=[target_user_id])
    comic = db.relationship('Comic', backref=db.backref('activities', lazy=True))
    chapter = db.relationship('Chapter')
    reading_list = db.relationship('ReadingList')
    
    def __repr__(self):
        return f'<Activity {self.activity_type} by {self.user_id}>'
    
    def to_dict(self):
        """Convert activity to dictionary"""
        data = {
            'id': self.id,
            'user_id': self.user_id,
            'user': {
                'id': self.user.id,
                'username': self.user.username,
                'avatar': self.user.avatar
            },
            'activity_type': self.activity_type,
            'is_public': self.is_public,
            'created_at': self.created_at.isoformat()
        }
        if self.comic:
            data['comic'] = {
                'id': self.comic.id,
                'title': self.comic.title,
                'cover_image': self.comic.cover_image
            }
        if self.chapter:
            data['chapter'] = {
                'id': self.chapter.id,
                'title': self.chapter.title,
                'number': self.chapter.number
            }
        if self.target_user:
            data['target_user'] = {
                'id': self.target_user.id,
                'username': self.target_user.username,
                'avatar': self.target_user.avatar
            }
        if self.reading_list:
            data['reading_list'] = {
                'id': self.reading_list.id,
                'title': self.reading_list.title
            }
        if self.data:
            data['data'] = self.data
        return data


class Follow(db.Model):
    """Follow model for user following relationships"""
    id = db.Column(db.Integer, primary_key=True)
    follower_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    following_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    follower = db.relationship('User', foreign_keys=[follower_id], backref=db.backref('following', lazy=True))
    following = db.relationship('User', foreign_keys=[following_id], backref=db.backref('followers', lazy=True))
    
    # Unique constraint to prevent duplicate follows
    __table_args__ = (db.UniqueConstraint('follower_id', 'following_id', name='unique_follow'),)
    
    def __repr__(self):
        return f'<Follow {self.follower_id} -> {self.following_id}>'


class Bookmark(db.Model):
    """Bookmark model for saving reading positions"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    comic_id = db.Column(db.Integer, db.ForeignKey('comic.id'), nullable=False)
    chapter_id = db.Column(db.Integer, db.ForeignKey('chapter.id'), nullable=True)
    page_number = db.Column(db.Integer, nullable=False, default=1)
    note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', backref=db.backref('bookmarks', lazy=True))
    comic = db.relationship('Comic', backref=db.backref('bookmarks', lazy=True, cascade='all, delete-orphan'))
    chapter = db.relationship('Chapter', backref=db.backref('bookmarks', lazy=True))
    
    # Unique constraint to prevent duplicate bookmarks at same position
    __table_args__ = (db.UniqueConstraint('user_id', 'comic_id', 'chapter_id', 'page_number', name='unique_bookmark'),)
    
    def __repr__(self):
        return f'<Bookmark user={self.user_id} comic={self.comic_id} page={self.page_number}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'comic_id': self.comic_id,
            'chapter_id': self.chapter_id,
            'page_number': self.page_number,
            'note': self.note,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'comic_title': self.comic.title if self.comic else None,
            'chapter_title': self.chapter.title if self.chapter else None,
            'chapter_number': self.chapter.number if self.chapter else None
        }


class ReadingProgress(db.Model):
    """Reading progress tracking for user reading history"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    comic_id = db.Column(db.Integer, db.ForeignKey('comic.id'), nullable=False)
    chapter_id = db.Column(db.Integer, db.ForeignKey('chapter.id'), nullable=True)
    page_number = db.Column(db.Integer, nullable=False, default=1)
    total_pages = db.Column(db.Integer, nullable=False, default=1)
    percent_complete = db.Column(db.Float, nullable=False, default=0.0)
    last_read_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    total_time_spent = db.Column(db.Integer, nullable=False, default=0)  # in seconds
    completed = db.Column(db.Boolean, nullable=False, default=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    # Relationships are defined on parent models (User, Comic, Chapter) with backrefs
    
    # Unique constraint - one progress per user/comic/chapter
    __table_args__ = (db.UniqueConstraint('user_id', 'comic_id', 'chapter_id', name='unique_reading_progress'),)
    
    def __repr__(self):
        return f'<ReadingProgress user={self.user_id} comic={self.comic_id} page={self.page_number}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'comic_id': self.comic_id,
            'chapter_id': self.chapter_id,
            'page_number': self.page_number,
            'total_pages': self.total_pages,
            'percent_complete': self.percent_complete,
            'last_read_at': self.last_read_at.isoformat() if self.last_read_at else None,
            'total_time_spent': self.total_time_spent,
            'completed': self.completed,
            'comic_title': self.comic.title if self.comic else None,
            'comic_cover': self.comic.cover_image if self.comic else None,
            'chapter_title': self.chapter.title if self.chapter else None,
            'chapter_number': self.chapter.number if self.chapter else None
        }
    
    def update_progress(self, page_number, total_pages, time_spent=0):
        """Update reading progress"""
        self.page_number = page_number
        self.total_pages = max(total_pages, 1)
        self.percent_complete = min(100.0, (page_number / self.total_pages) * 100)
        self.last_read_at = datetime.utcnow()
        self.total_time_spent += time_spent
        
        if self.percent_complete >= 95:
            self.completed = True
            if not self.completed_at:
                self.completed_at = datetime.utcnow()
        else:
            self.completed = False
            self.completed_at = None

    @property
    def current_page(self):
        return self.page_number

    @current_page.setter
    def current_page(self, value):
        self.page_number = value

    @property
    def percentage(self):
        return self.percent_complete

    @property
    def last_read(self):
        return self.last_read_at

    @last_read.setter
    def last_read(self, value):
        self.last_read_at = value

    @property
    def time_spent(self):
        return self.total_time_spent

    @time_spent.setter
    def time_spent(self, value):
        self.total_time_spent = value

    def update_percentage(self):
        """Calculate percentage and update completion status"""
        if self.total_pages and self.total_pages > 0:
            self.percent_complete = min(100.0, (self.page_number / self.total_pages) * 100)
        else:
            self.percent_complete = 0.0
            
        if self.percent_complete >= 95:
            self.completed = True
            if not self.completed_at:
                self.completed_at = datetime.utcnow()
        else:
            self.completed = False
            self.completed_at = None