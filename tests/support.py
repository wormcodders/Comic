import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flask import g
from werkzeug.security import generate_password_hash
from config import TestingConfig
from main import create_app
from models import db, User, Comic, Chapter, Comment, ReadingList


ROOT = Path(__file__).resolve().parents[1]
PASSWORD_HASHES = {name: generate_password_hash(password) for name, password in {
    "reader": "ReaderPass123", "visitor": "VisitorPass123", "operator": "OperatorPass123"
}.items()}
ANSWER_HASH = generate_password_hash("my favorite show")


class AppTestCase(unittest.TestCase):
    def setUp(self):
        (ROOT / "scratch").mkdir(exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(prefix="comicvault-tests-", dir=ROOT / "scratch")
        self.addCleanup(self.temp_dir.cleanup)
        upload_root = Path(self.temp_dir.name) / "static" / "uploads"

        class IsolatedConfig(TestingConfig):
            SECRET_KEY = "isolated-tests-secret-key-at-least-32-characters"
            RATELIMIT_ENABLED = False
            UPLOAD_FOLDER = str(upload_root)
            COMIC_UPLOAD_FOLDER = str(upload_root / "comics")
            COVER_UPLOAD_FOLDER = str(upload_root / "covers")

        self.config_class = IsolatedConfig
        with contextlib.redirect_stdout(io.StringIO()):
            self.app = create_app(IsolatedConfig)
        self.app.static_folder = str(upload_root.parent)
        for directory in (upload_root / "comics", upload_root / "covers", upload_root / "pages"):
            directory.mkdir(parents=True, exist_ok=True)
        self.client = self.app.test_client()
        self.context = self.app.app_context()
        self.context.push()
        self.addCleanup(self.context.pop)
        self.addCleanup(db.session.remove)
        self.error_log_patch = patch("routes.log_error")
        self.error_logs = self.error_log_patch.start()
        self.addCleanup(self.error_log_patch.stop)
        self.network_patch = patch("requests.sessions.Session.request", side_effect=AssertionError("Live network requests are forbidden in tests"))
        self.network_patch.start()
        self.addCleanup(self.network_patch.stop)

        def clear_cached_test_user():
            g.pop("_login_user", None)
        self.app.before_request_funcs[None].insert(0, clear_cached_test_user)

        self.owner = User(username="reader", email="reader@example.com")
        self.owner.password_hash = PASSWORD_HASHES["reader"]
        self.owner.security_answer_hash = ANSWER_HASH
        self.other = User(username="visitor", email="visitor@example.com")
        self.other.password_hash = PASSWORD_HASHES["visitor"]
        self.admin = User(username="operator", email="operator@example.com", is_admin=True)
        self.admin.password_hash = PASSWORD_HASHES["operator"]
        db.session.add_all([self.owner, self.other, self.admin])
        db.session.flush()
        self.public = Comic(title="Public comic", author="Writer", category="Action", visibility="public", pdf_file="public.pdf", uploader_id=self.owner.id)
        self.private = Comic(title="Private comic", author="Writer", category="Action", visibility="private", pdf_file="private.pdf", uploader_id=self.owner.id)
        self.draft = Comic(title="Draft comic", category="Action", visibility="draft", is_published=False, pdf_file="draft.pdf", uploader_id=self.owner.id)
        self.unpublished = Comic(title="Unpublished comic", category="Action", visibility="public", is_published=False, uploader_id=self.owner.id)
        db.session.add_all([self.public, self.private, self.draft, self.unpublished])
        db.session.flush()
        self.chapter = Chapter(comic_id=self.public.id, chapter_number=1, title="First chapter", page_count=10)
        self.next_chapter = Chapter(comic_id=self.public.id, chapter_number=2, title="Second chapter", page_count=10)
        self.private_chapter = Chapter(comic_id=self.private.id, chapter_number=1, title="Private chapter")
        self.comment = Comment(user_id=self.owner.id, comic_id=self.public.id, content="Hello")
        self.hidden_comment = Comment(user_id=self.owner.id, comic_id=self.public.id, content="Hidden text", is_hidden=True)
        self.private_comment = Comment(user_id=self.owner.id, comic_id=self.private.id, content="Private text")
        self.reading_list = ReadingList(user_id=self.owner.id, title="My comics", is_public=True)
        self.private_list = ReadingList(user_id=self.owner.id, title="My secret comics", is_public=False)
        db.session.add_all([self.chapter, self.next_chapter, self.private_chapter, self.comment, self.hidden_comment, self.private_comment, self.reading_list, self.private_list])
        db.session.commit()

    def login_as(self, user):
        with self.client.session_transaction() as session:
            session.clear()
            session["_user_id"] = user.get_id()
            session["_fresh"] = True

    def assert_status(self, response, status):
        error = self.error_logs.call_args[0][0] if self.error_logs.call_args else ""
        self.assertEqual(response.status_code, status, f"{type(error).__name__}: {error}; {response.get_data(as_text=True)[:100]}")
