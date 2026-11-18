"""
Security Utilities for ComicVault
Includes guards for SSRF, Path Traversal, HTML Injection (XSS), and Safe File Resolution.
"""

import os
import socket
import ipaddress
import urllib.parse
import re
from werkzeug.utils import secure_filename
import bleach

class UnsafeURLError(ValueError):
    """An outbound URL is malformed or reaches a restricted destination."""


def resolve_safe_url(url: str, allow_local: bool = False):
    """Validate a destination and return its parsed URL and vetted IPs.

    Outbound callers must connect to these IPs rather than resolve the host again.
    Local LLM mode permits private/loopback addresses, but never metadata endpoints.
    """
    if not isinstance(url, str) or not url or len(url) > 2048 or url != url.strip() or '\\' in url or any(ord(char) < 33 or ord(char) == 127 for char in url):
        raise UnsafeURLError('Invalid remote URL')
    try:
        parsed = urllib.parse.urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        if parsed.scheme not in ('http', 'https') or not hostname or '%' in hostname or parsed.username is not None or parsed.password is not None:
            raise UnsafeURLError('Only HTTP(S) URLs without embedded credentials are allowed')
        blocked = {'metadata.google.internal', 'instance-data', '169.254.169.254'}
        if hostname.lower().rstrip('.') in blocked:
            raise UnsafeURLError('Restricted remote destination')
        entries = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        addresses = list(dict.fromkeys(entry[4][0] for entry in entries))
        if not addresses:
            raise UnsafeURLError('Remote destination could not be resolved')
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if ip.is_link_local or ip.is_multicast or ip.is_unspecified or (ip.is_reserved and not (allow_local and ip.is_loopback)) or getattr(ip, 'is_site_local', False):
                raise UnsafeURLError('Restricted remote destination')
            if not ip.is_global and not (allow_local and (ip.is_private or ip.is_loopback)):
                raise UnsafeURLError('Restricted remote destination')
        # Prefer IPv4 on hosts with no IPv6 connectivity; keep every address vetted.
        addresses.sort(key=lambda address: ':' in address)
        return parsed, addresses
    except (ValueError, OSError, UnicodeError) as error:
        if isinstance(error, UnsafeURLError):
            raise
        raise UnsafeURLError('Invalid or unresolvable remote URL') from error


def is_safe_url(url: str, allow_local: bool = False) -> bool:
    try:
        resolve_safe_url(url, allow_local)
        return True
    except UnsafeURLError:
        return False


def is_safe_redirect_target(target: str) -> bool:
    if not isinstance(target, str) or not target.startswith('/'):
        return False
    decoded = urllib.parse.unquote(urllib.parse.unquote(target))
    if decoded.startswith('//') or '\\' in decoded or any(ord(char) < 32 or ord(char) == 127 for char in decoded):
        return False
    parsed = urllib.parse.urlsplit(decoded)
    return not parsed.scheme and not parsed.netloc and parsed.path.startswith('/')


def is_safe_path(base_dir: str, target_path: str) -> bool:
    """
    Verify that target_path is strictly within base_dir, preventing path traversal attacks.
    """
    try:
        base_abs = os.path.normcase(os.path.realpath(base_dir))
        target_abs = os.path.normcase(os.path.realpath(target_path))
        return os.path.commonpath([base_abs, target_abs]) == base_abs
    except Exception:
        return False


def safe_join_path(base_dir: str, untrusted_filename: str) -> str:
    """
    Sanitize an untrusted filename and join it with base_dir.
    Returns the resolved path if safe and inside base_dir, or None if invalid.
    """
    if not isinstance(untrusted_filename, str) or not untrusted_filename or any(char in untrusted_filename for char in ('/', '\\', ':', '\x00')) or untrusted_filename in ('.', '..'):
        return None
    
    clean_name = secure_filename(os.path.basename(untrusted_filename))
    if not clean_name:
        return None

    candidate_path = os.path.abspath(os.path.join(base_dir, clean_name))
    if not is_safe_path(base_dir, candidate_path):
        return None

    return candidate_path


def sanitize_plain_text(text: str, max_length: int = None) -> str:
    """
    Clean and sanitize plain-text user inputs (comments, list titles, reviews) by stripping
    all HTML/script tags to prevent stored XSS.
    """
    if not text:
        return ""
    
    # Strip all HTML tags
    cleaned = bleach.clean(str(text), tags=[], attributes={}, strip=True).strip()
    
    if max_length and len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
        
    return cleaned


# =====================================================================
# Strict Input Validation Helpers (Fixed Lengths & Regex Enforcements)
# =====================================================================

USERNAME_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{3,20}$')
EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$')
PASSWORD_PATTERN = re.compile(r'^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9!@#$%^&*()_+\-=[\]{}|;:,.<>?]{8,32}$')
SECURITY_ANSWER_PATTERN = re.compile(r'^[a-zA-Z0-9 ]{1,20}$')


def validate_username(username: str) -> tuple[bool, str]:
    """Validate username: alphanumeric, underscore, hyphen, 3 to 20 characters"""
    if not isinstance(username, str) or not username:
        return False, "Username is required."
    val = username.strip()
    if len(val) < 3 or len(val) > 20:
        return False, "Username must be between 3 and 20 characters."
    if not USERNAME_PATTERN.fullmatch(val):
        return False, "Username can only contain letters, numbers, underscores, and hyphens."
    return True, ""


def validate_email(email: str) -> tuple[bool, str]:
    """Validate email address format and length (max 50 chars)"""
    if not isinstance(email, str) or not email:
        return False, "Email address is required."
    val = email.strip()
    if len(val) < 5 or len(val) > 50:
        return False, "Email must be between 5 and 50 characters."
    if not EMAIL_PATTERN.fullmatch(val):
        return False, "Please enter a valid email address."
    return True, ""


def validate_password(password: str) -> tuple[bool, str]:
    """Validate password: 8 to 32 characters, at least 1 letter and 1 number"""
    if not isinstance(password, str) or not password:
        return False, "Password is required."
    if len(password) < 8 or len(password) > 32:
        return False, "Password must be between 8 and 32 characters."
    if not PASSWORD_PATTERN.fullmatch(password):
        return False, "Password must contain at least one letter and at least one number."
    return True, ""


def validate_security_answer(answer: str) -> tuple[bool, str]:
    """Validate childhood favourite TV show: letters, numbers, space only, max 20 chars"""
    if not isinstance(answer, str) or not answer:
        return False, "Security answer is required."
    raw = str(answer)
    if len(raw) < 1 or len(raw) > 20:
        return False, "Security answer must be between 1 and 20 characters."
    if not SECURITY_ANSWER_PATTERN.fullmatch(raw):
        return False, "Security answer can only contain letters, numbers, and spaces."
    if not raw.strip():
        return False, "Security answer cannot be blank spaces."
    return True, ""

