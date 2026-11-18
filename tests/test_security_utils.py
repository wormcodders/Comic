import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask
import requests

from app_setup import configure_security
from crypto_utils import encrypt_val, decrypt_val
from network_utils import safe_request, PinnedAddressAdapter
from security_utils import is_safe_url, is_safe_path, safe_join_path, is_safe_redirect_target, UnsafeURLError


def address_info(address):
    family = socket.AF_INET6 if ':' in address else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 6, '', (address, 443))]


def response(status=200, body=b'ok', headers=None):
    result = requests.Response()
    result.status_code = status
    result._content = body
    result._content_consumed = True
    result.headers.update(headers or {})
    return result


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.adapters = []
        self.trust_env = True
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def mount(self, prefix, adapter):
        self.adapters.append(adapter)

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return next(self.responses)


class NetworkSecurityTests(unittest.TestCase):
    def test_non_public_addresses_are_blocked(self):
        for address in ('127.0.0.1', '10.0.0.1', '169.254.169.254', '100.64.0.1', '0.0.0.0', '224.0.0.1', '::1', '::ffff:127.0.0.1'):
            with self.subTest(address=address), patch('security_utils.socket.getaddrinfo', return_value=address_info(address)):
                self.assertFalse(is_safe_url('https://example.com/file.pdf'))

    def test_mixed_public_and_private_dns_is_blocked(self):
        with patch('security_utils.socket.getaddrinfo', return_value=address_info('93.184.216.34') + address_info('10.0.0.1')):
            self.assertFalse(is_safe_url('https://example.com/file.pdf'))

    def test_local_llm_mode_never_allows_metadata(self):
        with patch('security_utils.socket.getaddrinfo', return_value=address_info('169.254.169.254')):
            self.assertFalse(is_safe_url('http://example.com/', allow_local=True))
        with patch('security_utils.socket.getaddrinfo', return_value=address_info('127.0.0.1')):
            self.assertTrue(is_safe_url('http://localhost:11434/v1', allow_local=True))

    def test_malformed_and_credential_urls_are_blocked(self):
        for url in ('file:///etc/passwd', 'https://user:pass@example.com/', 'https://example.com:bad/', 'https://example.com\\@localhost/', 'https://example.com/\n', ' https://example.com/'):
            with self.subTest(url=url):
                self.assertFalse(is_safe_url(url))

    def test_redirect_to_private_address_is_not_requested(self):
        session = FakeSession([response(302, headers={'Location': 'http://127.0.0.1/private'})])
        with patch('network_utils.requests.Session', return_value=session), patch('security_utils.socket.getaddrinfo', side_effect=[address_info('93.184.216.34'), address_info('127.0.0.1')]):
            with self.assertRaises(UnsafeURLError):
                safe_request('GET', 'https://example.com/file.pdf')
        self.assertEqual(len(session.calls), 1)
        self.assertFalse(session.calls[0][2]['allow_redirects'])
        self.assertFalse(session.trust_env)
        self.assertTrue(session.closed)

    def test_credential_posts_do_not_follow_redirects(self):
        session = FakeSession([response(307, headers={'Location': 'https://elsewhere.example/'})])
        with patch('network_utils.requests.Session', return_value=session), patch('security_utils.socket.getaddrinfo', return_value=address_info('93.184.216.34')):
            with self.assertRaises(UnsafeURLError):
                safe_request('POST', 'https://example.com/api', data={'token': 'private'})
        self.assertEqual(len(session.calls), 1)

    def test_response_size_is_bounded_with_and_without_content_length(self):
        for headers in ({}, {'Content-Length': '1000'}):
            with self.subTest(headers=headers):
                session = FakeSession([response(body=b'x' * 100, headers=headers)])
                with patch('network_utils.requests.Session', return_value=session), patch('security_utils.socket.getaddrinfo', return_value=address_info('93.184.216.34')):
                    with self.assertRaises(ValueError):
                        safe_request('GET', 'https://example.com/file', max_bytes=10)

    def test_dns_address_is_pinned_and_tls_checks_original_hostname(self):
        session = FakeSession([response()])
        with patch('network_utils.requests.Session', return_value=session), patch('security_utils.socket.getaddrinfo', return_value=address_info('93.184.216.34')) as dns:
            result = safe_request('GET', 'https://example.com/file')
        self.assertEqual(result.content, b'ok')
        self.assertEqual(dns.call_count, 1)
        adapter = session.adapters[0]
        prepared = requests.Request('GET', 'https://example.com/file').prepare()
        pool = adapter.get_connection_with_tls_context(prepared, True)
        self.assertEqual(pool.host, '93.184.216.34')
        self.assertEqual(pool.assert_hostname, 'example.com')
        self.assertEqual(pool.conn_kw['server_hostname'], 'example.com')
        self.assertEqual(session.calls[0][2]['headers']['Host'], 'example.com')


class ConfigurationAndCryptoTests(unittest.TestCase):
    def test_production_rejects_missing_and_placeholder_secrets(self):
        for secret in (None, 'short', 'dev-secret-key-change-in-production', 'change-this-secret-key-in-production'):
            with self.subTest(secret=secret):
                app = Flask(__name__)
                app.config.update(ENV_NAME='production', SECRET_KEY=secret, RATELIMIT_STORAGE_URI='redis://localhost:6379/0')
                with self.assertRaises(RuntimeError):
                    configure_security(app)

    def test_production_rejects_process_local_rate_storage(self):
        app = Flask(__name__)
        app.config.update(ENV_NAME='production', SECRET_KEY='strong-production-secret-with-32-characters', RATELIMIT_STORAGE_URI='memory://')
        with self.assertRaises(RuntimeError):
            configure_security(app)

    def test_development_secret_persists_without_a_known_default(self):
        with tempfile.TemporaryDirectory() as directory:
            apps = [Flask(__name__, instance_path=directory), Flask(__name__, instance_path=directory)]
            for app in apps:
                configure_security(app)
            self.assertEqual(apps[0].secret_key, apps[1].secret_key)
            self.assertGreaterEqual(len(apps[0].secret_key), 32)
            self.assertNotEqual(apps[0].secret_key, 'dev-secret-key-change-in-production')

    def test_encryption_uses_the_active_application_key(self):
        app = Flask(__name__)
        app.secret_key = 'first-application-key-with-more-than-32-characters'
        with app.app_context():
            encrypted = encrypt_val('private-api-key')
            self.assertNotIn('private-api-key', encrypted)
            self.assertEqual(decrypt_val(encrypted), 'private-api-key')
            app.secret_key = 'second-application-key-with-more-than-32-characters'
            with self.assertRaises(ValueError):
                decrypt_val(encrypted)

    def test_crypto_never_silently_returns_plaintext_on_failure(self):
        with patch('crypto_utils.get_cipher', side_effect=RuntimeError('No cipher')):
            with self.assertRaises(RuntimeError):
                encrypt_val('private-api-key')
        app = Flask(__name__)
        app.secret_key = 'configured-key-with-more-than-32-characters'
        with app.app_context(), self.assertRaises(ValueError):
            decrypt_val('enc:corrupt-ciphertext')


class PathTests(unittest.TestCase):
    def test_traversal_and_windows_alternate_streams_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ('../secret.pdf', '..\\secret.pdf', 'file.pdf:secret', '/etc/passwd', 'C:\\secret.pdf', '.', '..', '\x00file.pdf'):
                with self.subTest(name=name):
                    self.assertIsNone(safe_join_path(directory, name))
            self.assertIsNotNone(safe_join_path(directory, 'comic.pdf'))

    def test_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / 'uploads'
            outside = Path(directory) / 'outside'
            base.mkdir()
            outside.mkdir()
            try:
                os.symlink(outside, base / 'link', target_is_directory=True)
            except OSError:
                self.skipTest('Symlink creation is unavailable on this host')
            self.assertFalse(is_safe_path(str(base), str(base / 'link' / 'secret.pdf')))

    def test_login_redirects_stay_on_the_application(self):
        self.assertTrue(is_safe_redirect_target('/library?page=2'))
        for target in ('//evil.example', '/\\evil.example', '/%5cevil.example', '/%2f%2fevil.example', 'https://evil.example', '/\nLocation: evil'):
            with self.subTest(target=target):
                self.assertFalse(is_safe_redirect_target(target))
