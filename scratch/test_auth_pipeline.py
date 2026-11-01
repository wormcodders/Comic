"""
Test Suite for Registration Validation and Forgot Password Pipeline
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + '/..'))

from main import create_app
from config import TestingConfig
from models import db, User
from security_utils import (
    validate_username,
    validate_email,
    validate_password,
    validate_security_answer
)


class AuthPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(TestingConfig)
        cls.client = cls.app.test_client()
        with cls.app.app_context():
            db.create_all()

    def setUp(self):
        with self.app.app_context():
            # Clean up existing test users if any
            User.query.filter(User.username.in_(['speedy_sam', 'reset_tester', 'bad_user'])).delete()
            db.session.commit()

    # --- 1. Unit Tests for Field Validation Helpers ---
    def test_username_validation(self):
        self.assertTrue(validate_username('valid_user12')[0])
        self.assertTrue(validate_username('user-name')[0])
        self.assertFalse(validate_username('ab')[0])  # < 3
        self.assertFalse(validate_username('a' * 21)[0])  # > 20
        self.assertFalse(validate_username('user@name')[0])  # invalid symbol
        self.assertFalse(validate_username('user name')[0])  # space not allowed

    def test_email_validation(self):
        self.assertTrue(validate_email('user@example.com')[0])
        self.assertTrue(validate_email('test.user+tag@domain.co.uk')[0])
        self.assertFalse(validate_email('invalid-email')[0])
        self.assertFalse(validate_email('a' * 45 + '@example.com')[0])  # > 50

    def test_password_validation(self):
        self.assertTrue(validate_password('Secret123!')[0])
        self.assertTrue(validate_password('pass1234')[0])
        self.assertFalse(validate_password('short1')[0])  # < 8
        self.assertFalse(validate_password('a' * 35)[0])  # > 32
        self.assertFalse(validate_password('alllettersonly')[0])  # no digit
        self.assertFalse(validate_password('1234567890')[0])  # no letter

    def test_security_answer_validation(self):
        self.assertTrue(validate_security_answer('Tom and Jerry')[0])
        self.assertTrue(validate_security_answer('Ben 10')[0])
        self.assertTrue(validate_security_answer('Pokemon')[0])
        self.assertFalse(validate_security_answer('')[0])  # empty
        self.assertFalse(validate_security_answer('   ')[0])  # blank
        self.assertFalse(validate_security_answer('Ben_10!')[0])  # symbols not allowed
        self.assertFalse(validate_security_answer('A' * 21)[0])  # > 20

    # --- 2. Registration Route Tests ---
    def test_registration_with_security_question(self):
        """Registering with valid fields saves hashed security answer and password"""
        response = self.client.post('/register', data={
            'username': 'speedy_sam',
            'email': 'speedy@example.com',
            'password': 'SecurePassword123',
            'confirm_password': 'SecurePassword123',
            'security_answer': 'Dragon Ball Z',
            'age_confirm': '1'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            user = User.query.filter_by(username='speedy_sam').first()
            self.assertIsNotNone(user)
            self.assertTrue(user.check_password('SecurePassword123'))
            # Check security answer hash is stored, not plaintext
            self.assertIsNotNone(user.security_answer_hash)
            self.assertNotEqual(user.security_answer_hash, 'Dragon Ball Z')
            self.assertNotIn('Dragon Ball Z', user.security_answer_hash)
            self.assertTrue(user.check_security_answer('dragon ball z'))
            self.assertTrue(user.check_security_answer('  DRAGON   BALL   Z  '))
            self.assertFalse(user.check_security_answer('Pokemon'))

    def test_registration_requires_18_plus_confirmation(self):
        """Registration fails if 18+ checkbox is not checked"""
        resp = self.client.post('/register', data={
            'username': 'underage_sam',
            'email': 'underage@example.com',
            'password': 'SecurePassword123',
            'confirm_password': 'SecurePassword123',
            'security_answer': 'Dragon Ball Z'
            # age_confirm omitted
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'You must confirm that you are 18+', resp.data)

    def test_registration_rejects_invalid_inputs(self):
        """Registration rejects bad symbols in username, passwords mismatch, etc."""
        # Symbol in username
        resp = self.client.post('/register', data={
            'username': 'bad@user',
            'email': 'bad@example.com',
            'password': 'SecurePassword123',
            'confirm_password': 'SecurePassword123',
            'security_answer': 'Pokemon'
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Username can only contain letters', resp.data)

        # Disallowed symbols in security answer
        resp2 = self.client.post('/register', data={
            'username': 'speedy_sam2',
            'email': 'bad2@example.com',
            'password': 'SecurePassword123',
            'confirm_password': 'SecurePassword123',
            'security_answer': 'Pokemon#1'
        })
        self.assertEqual(resp2.status_code, 200)
        self.assertIn(b'Security answer can only contain letters, numbers, and spaces', resp2.data)

    # --- 3. Forgot Password Pipeline Tests ---
    def test_full_forgot_password_flow(self):
        """Test full password reset pipeline from verification to setting new password"""
        with self.app.app_context():
            user = User(username='reset_tester', email='reset@example.com')
            user.set_password('OldPassword123')
            user.set_security_answer('Dexter Lab')
            db.session.add(user)
            db.session.commit()

        # Step 1: Submit wrong answer
        fail_resp = self.client.post('/forgot-password', data={
            'email': 'reset@example.com',
            'security_answer': 'Wrong Show'
        })
        self.assertIn(b'Invalid email or security answer', fail_resp.data)

        # Step 2: Submit correct answer (with different casing and extra spaces)
        succ_resp = self.client.post('/forgot-password', data={
            'email': 'reset@example.com',
            'security_answer': '  DEXTER   LAB  '
        })
        self.assertEqual(succ_resp.status_code, 302)
        redirect_url = succ_resp.headers.get('Location')
        self.assertIn('/reset-password?token=', redirect_url)

        # Extract token from redirect URL
        token = redirect_url.split('token=')[1]

        # Step 3: Access reset password page with token
        form_resp = self.client.get(f'/reset-password?token={token}')
        self.assertEqual(form_resp.status_code, 200)
        self.assertIn(b'Set New Password', form_resp.data)

        # Step 4: Submit new password
        reset_post = self.client.post('/reset-password', data={
            'token': token,
            'password': 'BrandNewPassword999',
            'confirm_password': 'BrandNewPassword999'
        }, follow_redirects=True)
        self.assertEqual(reset_post.status_code, 200)
        self.assertIn(b'Password reset successful', reset_post.data)

        # Step 5: Verify new password works in database
        with self.app.app_context():
            updated_user = User.query.filter_by(username='reset_tester').first()
            self.assertFalse(updated_user.check_password('OldPassword123'))
            self.assertTrue(updated_user.check_password('BrandNewPassword999'))

        # Step 6: Verify old token cannot be reused
        reuse_resp = self.client.get(f'/reset-password?token={token}', follow_redirects=True)
        self.assertIn(b'expired or has already been used', reuse_resp.data)


if __name__ == '__main__':
    unittest.main()
