"""
Security Utilities for ComicVault
Includes guards for SSRF, Path Traversal, HTML Injection (XSS), and Safe File Resolution.
"""

import os
import socket
import ipaddress
import urllib.parse
from werkzeug.utils import secure_filename
import bleach

def is_safe_url(url: str, allow_local: bool = False) -> bool:
    """
    Validate that a URL is safe to download from and cannot be used for SSRF attacks.
    Blocks private IP ranges (RFC 1918), loopback (127.0.0.1), link-local / cloud metadata (169.254.169.254),
    and reserved/multicast addresses.
    """
    if not url or not isinstance(url, str):
        return False

    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False

        hostname = parsed.hostname
        if not hostname:
            return False

        hostname_lower = hostname.lower().strip('. ')

        # Explicitly block known internal or metadata hostnames
        blocked_hosts = {
            'localhost',
            'metadata.google.internal',
            'instance-data',
            '169.254.169.254',
            '0.0.0.0',
            '::',
            '::1'
        }
        if hostname_lower in blocked_hosts and not allow_local:
            return False

        # Resolve host addresses
        try:
            addr_info = socket.getaddrinfo(hostname, None)
        except (socket.gaierror, socket.herror, UnicodeError):
            return False

        if not addr_info:
            return False

        for entry in addr_info:
            ip_str = entry[4][0]
            ip = ipaddress.ip_address(ip_str)

            if not allow_local:
                if (ip.is_loopback or 
                    ip.is_private or 
                    ip.is_link_local or 
                    ip.is_reserved or 
                    ip.is_unspecified or 
                    ip.is_multicast):
                    return False

        return True

    except Exception:
        return False


def is_safe_path(base_dir: str, target_path: str) -> bool:
    """
    Verify that target_path is strictly within base_dir, preventing path traversal attacks.
    """
    try:
        base_abs = os.path.abspath(base_dir)
        target_abs = os.path.abspath(target_path)
        return os.path.commonpath([base_abs, target_abs]) == base_abs
    except Exception:
        return False


def safe_join_path(base_dir: str, untrusted_filename: str) -> str:
    """
    Sanitize an untrusted filename and join it with base_dir.
    Returns the resolved path if safe and inside base_dir, or None if invalid.
    """
    if not untrusted_filename:
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

import re

USERNAME_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{3,20}$')
EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$')
PASSWORD_PATTERN = re.compile(r'^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9!@#$%^&*()_+\-=[\]{}|;:,.<>?]{8,32}$')
SECURITY_ANSWER_PATTERN = re.compile(r'^[a-zA-Z0-9 ]{1,20}$')


def validate_username(username: str) -> tuple[bool, str]:
    """Validate username: alphanumeric, underscore, hyphen, 3 to 20 characters"""
    if not username:
        return False, "Username is required."
    val = username.strip()
    if len(val) < 3 or len(val) > 20:
        return False, "Username must be between 3 and 20 characters."
    if not USERNAME_PATTERN.match(val):
        return False, "Username can only contain letters, numbers, underscores, and hyphens."
    return True, ""


def validate_email(email: str) -> tuple[bool, str]:
    """Validate email address format and length (max 50 chars)"""
    if not email:
        return False, "Email address is required."
    val = email.strip()
    if len(val) < 5 or len(val) > 50:
        return False, "Email must be between 5 and 50 characters."
    if not EMAIL_PATTERN.match(val):
        return False, "Please enter a valid email address."
    return True, ""


def validate_password(password: str) -> tuple[bool, str]:
    """Validate password: 8 to 32 characters, at least 1 letter and 1 number"""
    if not password:
        return False, "Password is required."
    if len(password) < 8 or len(password) > 32:
        return False, "Password must be between 8 and 32 characters."
    if not PASSWORD_PATTERN.match(password):
        return False, "Password must contain at least one letter and at least one number."
    return True, ""


def validate_security_answer(answer: str) -> tuple[bool, str]:
    """Validate childhood favourite TV show: letters, numbers, space only, max 20 chars"""
    if not answer:
        return False, "Security answer is required."
    raw = str(answer)
    if len(raw) < 1 or len(raw) > 20:
        return False, "Security answer must be between 1 and 20 characters."
    if not SECURITY_ANSWER_PATTERN.match(raw):
        return False, "Security answer can only contain letters, numbers, and spaces."
    if not raw.strip():
        return False, "Security answer cannot be blank spaces."
    return True, ""

