"""
Security Patches & Verification Test Suite for ComicVault
Tests defensive controls: Path Traversal, SSRF Guard, XSS Sanitization, Rate Limiter, and RBAC.
"""

import os
import sys
import unittest
from flask import Flask

# Add root directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + '/..'))

from main import create_app
from config import TestingConfig
from models import db, User, Comic, Comment, ReadingList, Setting
from security_utils import is_safe_url, is_safe_path, safe_join_path, sanitize_plain_text


class SecurityVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(TestingConfig)
        cls.client = cls.app.test_client()
        with cls.app.app_context():
            db.create_all()
            
            # Create test admin
            cls.admin = User.query.filter_by(username='testadmin').first()
            if not cls.admin:
                cls.admin = User(username='testadmin', email='testadmin@example.com', is_admin=True)
                cls.admin.set_password('AdminPass123!')
                db.session.add(cls.admin)

            # Create normal user
            cls.user = User.query.filter_by(username='testuser').first()
            if not cls.user:
                cls.user = User(username='testuser', email='testuser@example.com', is_admin=False)
                cls.user.set_password('UserPass123!')
                db.session.add(cls.user)

            # Create test comic
            cls.comic = Comic.query.filter_by(title='Test Security Comic').first()
            if not cls.comic:
                cls.comic = Comic(
                    title='Test Security Comic',
                    pdf_file='safe_comic.pdf',
                    cover_image='cover.jpg',
                    description='A test comic for security verification'
                )
                db.session.add(cls.comic)

            db.session.commit()
            cls.admin_id = cls.admin.id
            cls.user_id = cls.user.id
            cls.comic_id = cls.comic.id

    # --- 1. SSRF Guard Tests ---
    def test_ssrf_blocks_private_and_loopback_ips(self):
        """Verify SSRF guardian blocks loopback, cloud metadata, and RFC 1918 ranges"""
        blocked_urls = [
            'http://127.0.0.1:5000/admin',
            'http://localhost:5000/admin',
            'http://169.254.169.254/latest/meta-data',
            'http://10.0.0.1/secret',
            'http://192.168.1.1/router',
            'http://172.16.0.1/internal',
            'ftp://files.catbox.moe/file.pdf',  # Disallowed scheme
            'file:///etc/passwd',               # Disallowed scheme
            'javascript:alert(1)',              # Disallowed scheme
        ]
        for url in blocked_urls:
            self.assertFalse(is_safe_url(url), f"SSRF Guard failed to block: {url}")

    def test_ssrf_allows_legitimate_public_urls(self):
        """Verify SSRF guardian allows public cloud endpoints"""
        allowed_urls = [
            'https://files.catbox.moe/abc123.pdf',
            'https://upfiles.com/upload',
            'https://google.com/test.pdf'
        ]
        for url in allowed_urls:
            self.assertTrue(is_safe_url(url), f"SSRF Guard incorrectly blocked valid URL: {url}")

    # --- 2. Path Traversal Guard Tests ---
    def test_path_traversal_guards(self):
        """Verify path traversal prevention functions"""
        base_dir = os.path.join(self.app.static_folder, 'uploads', 'comics')
        
        # Test path traversal attempts
        dangerous_paths = [
            '../../../config.py',
            '..\\..\\..\\config.py',
            '/etc/passwd',
            'C:\\Windows\\System32\\calc.exe',
            'subdir/../../../../config.py'
        ]
        
        for p in dangerous_paths:
            # safe_join_path must resolve to a safe base or return None/filename without escape
            resolved = safe_join_path(base_dir, p)
            if resolved:
                self.assertTrue(is_safe_path(base_dir, resolved), f"Path escaped base_dir: {resolved}")
                self.assertNotIn('..', resolved)

    # --- 3. Stored XSS / HTML Sanitization Tests ---
    def test_html_sanitization(self):
        """Verify HTML/script tags are completely stripped from user inputs"""
        dirty_inputs = [
            ('<script>alert("XSS")</script>Comic review', 'alert("XSS")Comic review'),
            ('<img src="x" onerror="alert(1)">Awesome book!', 'Awesome book!'),
            ('<a href="javascript:steal()">Click here</a>', 'Click here'),
            ('<b>Bold</b> <i>Italic</i> plain text', 'Bold Italic plain text'),
        ]
        for raw, expected in dirty_inputs:
            cleaned = sanitize_plain_text(raw)
            self.assertEqual(cleaned, expected, f"Failed to sanitize: {raw}")

    # --- 4. Endpoint Level Tests ---
    def test_admin_upload_to_host_blocks_ssrf(self):
        """Verify /admin/upload_to_host blocks SSRF attack payloads"""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin_id)
            sess['_fresh'] = True

        response = self.client.post('/admin/upload_to_host', json={
            'local_path': 'http://169.254.169.254/latest/meta-data'
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('Invalid or restricted remote URL', response.get_json()['message'])

    def test_admin_upload_to_host_blocks_path_traversal(self):
        """Verify /admin/upload_to_host blocks path traversal payloads"""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin_id)
            sess['_fresh'] = True

        response = self.client.post('/admin/upload_to_host', json={
            'local_path': '../../../config.py'
        })
        self.assertEqual(response.status_code, 404)

    def test_comment_creation_sanitizes_xss(self):
        """Verify comments created via API have script/HTML tags stripped"""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.user_id)
            sess['_fresh'] = True

        response = self.client.post(f'/api/comics/{self.comic_id}/comments', json={
            'content': '<script>stealCookie()</script>This comic is amazing!<img src=x onerror=alert(1)>'
        })
        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        self.assertNotIn('<script>', data['comment']['content'])
        self.assertNotIn('onerror', data['comment']['content'])
        self.assertEqual(data['comment']['content'], 'stealCookie()This comic is amazing!')

    def test_reading_list_creation_sanitizes_xss(self):
        """Verify reading lists have script/HTML tags stripped"""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.user_id)
            sess['_fresh'] = True

        response = self.client.post('/api/reading-lists', json={
            'title': '<script>alert("pwn")</script>Top SciFi',
            'description': '<b onmouseover="alert(1)">Best comics</b> ever'
        })
        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        self.assertNotIn('<script>', data['reading_list']['title'])
        self.assertNotIn('onmouseover', data['reading_list']['description'])
        self.assertEqual(data['reading_list']['title'], 'alert("pwn")Top SciFi')
        self.assertEqual(data['reading_list']['description'], 'Best comics ever')

    def test_rbac_unauthenticated_blocked(self):
        """Verify unauthenticated user cannot access admin dashboard"""
        with self.client.session_transaction() as sess:
            sess.clear()

        response = self.client.get('/admin/dashboard')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers.get('Location', ''))

    def test_rbac_regular_user_blocked_from_admin(self):
        """Verify regular user cannot access admin dashboard"""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.user_id)
            sess['_fresh'] = True

        response = self.client.get('/admin/dashboard')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/', response.headers.get('Location', ''))


if __name__ == '__main__':
    unittest.main()
