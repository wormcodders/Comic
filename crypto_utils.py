"""
Cryptographic utility module for ComicVault.
Provides encryption and decryption at rest for sensitive credentials (API tokens, keys, hashes)
stored in the database using authenticated symmetric encryption (Fernet / AES-128-CBC + HMAC-SHA256).
"""

import base64
import hashlib
import os
from typing import Optional
from cryptography.fernet import Fernet
from cryptography.fernet import InvalidToken

SENSITIVE_KEYS = {
    'llm_api_key',
    'upfiles_token',
    'catbox_userhash',
}

ENCRYPTION_PREFIX = "enc:"


def get_cipher() -> Fernet:
    """
    Derive a 32-byte URL-safe base64 key from SECRET_KEY.
    Ensures consistent encryption/decryption tied to the server secret key.
    """
    from flask import current_app, has_app_context
    if has_app_context():
        secret = current_app.config.get('CREDENTIAL_ENCRYPTION_KEY') or current_app.config.get('SECRET_KEY')
    else:
        secret = os.environ.get('CREDENTIAL_ENCRYPTION_KEY') or os.environ.get('SECRET_KEY')
    if not secret:
        raise ValueError('A configured encryption key is required')
    secret_bytes = secret.encode('utf-8') if isinstance(secret, str) else secret
    key_bytes = hashlib.sha256(secret_bytes).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)


def is_sensitive_key(key: Optional[str]) -> bool:
    """Check if a settings key contains sensitive credentials that should be encrypted."""
    if not key:
        return False
    k = key.lower().strip()
    if k in SENSITIVE_KEYS:
        return True
    if 'max_tokens' in k or 'token_count' in k:
        return False
    # Match sensitive credential suffixes/patterns
    return any(sub in k for sub in ('api_key', '_token', 'auth_token', 'access_token', 'userhash', 'secret', 'password'))


def encrypt_val(value: Optional[str]) -> Optional[str]:
    """
    Encrypt a plaintext string, prefixing with 'enc:'.
    If already encrypted or empty, returns as-is.
    """
    if not value:
        return value
    val_str = str(value).strip()
    if not val_str:
        return val_str
    if val_str.startswith(ENCRYPTION_PREFIX):
        decrypt_val(val_str)  # Never accept malformed or foreign ciphertext.
        return val_str
    cipher = get_cipher()
    ciphertext = cipher.encrypt(val_str.encode('utf-8')).decode('utf-8')
    return f"{ENCRYPTION_PREFIX}{ciphertext}"


def decrypt_val(value: Optional[str]) -> Optional[str]:
    """
    Decrypt a ciphertext string starting with 'enc:'.
    If not encrypted or empty, returns as-is.
    """
    if not value:
        return value
    val_str = str(value).strip()
    if not val_str.startswith(ENCRYPTION_PREFIX):
        return val_str
    try:
        cipher = get_cipher()
        raw_token = val_str[len(ENCRYPTION_PREFIX):]
        return cipher.decrypt(raw_token.encode('utf-8')).decode('utf-8')
    except (InvalidToken, UnicodeError, ValueError) as error:
        raise ValueError('Unable to decrypt the stored credential; check the configured encryption key.') from error
