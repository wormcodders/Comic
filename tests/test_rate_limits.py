import contextlib
import io
import unittest

from config import TestingConfig
from extensions import limiter
from main import create_app


class RateLimitTests(unittest.TestCase):
    def test_guest_uploads_do_not_crash_when_rate_limiting_is_enabled(self):
        class RateConfig(TestingConfig):
            RATELIMIT_ENABLED = True
            RATELIMIT_STORAGE_URI = 'memory://'
        app = create_app(RateConfig)
        try:
            self.assertEqual(app.test_client().post('/upload').status_code, 302)
        finally:
            with app.app_context():
                limiter.reset()

    def test_password_recovery_is_limited_by_account_across_ips(self):
        class RateConfig(TestingConfig):
            RATELIMIT_ENABLED = True
            RATELIMIT_STORAGE_URI = 'memory://'
        with contextlib.redirect_stdout(io.StringIO()):
            app = create_app(RateConfig)
        client = app.test_client()
        try:
            for index in range(5):
                result = client.post('/forgot-password', data={'email': 'nobody@example.test', 'security_answer': 'Cartoons'},
                                     environ_overrides={'REMOTE_ADDR': f'198.51.100.{index + 1}'})
                self.assertEqual(result.status_code, 200)
            result = client.post('/forgot-password', data={'email': 'nobody@example.test', 'security_answer': 'Cartoons'},
                                 environ_overrides={'REMOTE_ADDR': '203.0.113.2'})
            self.assertEqual(result.status_code, 429)
        finally:
            with app.app_context():
                limiter.reset()
