"""
Catbox.moe Cloud Storage Service for ComicVault
Handles direct in-memory and file uploads, file deletions, and connection tests.
API Docs: https://catbox.moe/tools.php
"""

import os
import re
import io
import time
import requests
import mimetypes
from typing import Optional, Tuple, Union, List
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

CATBOX_API_URL = "https://catbox.moe/user/api.php"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Global persistent session with connection pooling
_session: Optional[requests.Session] = None


def get_catbox_session() -> requests.Session:
    """Retrieve or create a reusable requests Session with connection pooling."""
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": BROWSER_USER_AGENT})
        adapter = HTTPAdapter(
            pool_connections=20,
            pool_maxsize=50,
            max_retries=Retry(total=2, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
        )
        _session.mount("https://", adapter)
        _session.mount("http://", adapter)
    return _session


def sanitize_cloud_filename(filename: Optional[str], default_ext: str = ".bin") -> str:
    """
    Sanitize filename to ensure safe ASCII characters and a valid extension.
    Guarantees extension is never lost even if the original name has non-ASCII characters.
    """
    if not filename:
        return f"file{default_ext}"
    name, ext = os.path.splitext(filename)
    clean_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', name).strip('_')
    if not clean_name:
        clean_name = "file"
    clean_ext = ext.lower().strip()
    if not clean_ext or not re.match(r'^\.[a-zA-Z0-9]+$', clean_ext):
        clean_ext = default_ext
    return f"{clean_name}{clean_ext}"


class CatboxService:
    """Service to interact with Catbox.moe API"""

    def __init__(self, userhash: Optional[str] = None):
        self.userhash = userhash.strip() if userhash else ""
        self.api_url = CATBOX_API_URL

    def upload_file(
        self,
        file_input: Union[str, bytes, io.BytesIO],
        filename: Optional[str] = None,
        userhash: Optional[str] = None,
        max_retries: int = 3
    ) -> Optional[str]:
        """
        Upload a file (path, bytes, or file-like object) directly to Catbox.moe.
        Includes automatic retry with exponential backoff, browser headers, and session reuse.

        Args:
            file_input: File path (str), raw bytes (bytes), or file-like buffer (io.BytesIO).
            filename: Desired filename (required if passing raw bytes or buffer).
            userhash: Optional override for the account userhash.
            max_retries: Number of retry attempts on network error or empty 200 response.

        Returns:
            Direct URL string (e.g. 'https://files.catbox.moe/xxxxxx.ext') on success,
            or None on failure.
        """
        active_userhash = userhash if userhash is not None else self.userhash
        active_userhash = active_userhash.strip() if active_userhash else ""

        # Prepare file bytes
        file_bytes = None
        raw_filename = filename or "file"

        if isinstance(file_input, str):
            if not os.path.exists(file_input):
                print(f"[CatboxService] Error: Local file does not exist: {file_input}")
                return None
            raw_filename = filename or os.path.basename(file_input)
            with open(file_input, "rb") as f:
                file_bytes = f.read()
        elif isinstance(file_input, (bytes, bytearray)):
            file_bytes = bytes(file_input)
        elif hasattr(file_input, "read"):
            if hasattr(file_input, "seek"):
                file_input.seek(0)
            file_bytes = file_input.read()
            if hasattr(file_input, "seek"):
                file_input.seek(0)
        else:
            print(f"[CatboxService] Error: Unsupported file input type: {type(file_input)}")
            return None

        if not file_bytes:
            print("[CatboxService] Error: Empty file payload.")
            return None

        # Guess mime type and sanitize target filename
        mime_type, _ = mimetypes.guess_type(raw_filename)
        default_ext = mimetypes.guess_extension(mime_type or "") or ".bin"
        target_filename = sanitize_cloud_filename(raw_filename, default_ext=default_ext)
        if not mime_type:
            mime_type = "application/octet-stream"

        session = get_catbox_session()

        for attempt in range(1, max_retries + 1):
            data = {"reqtype": "fileupload"}
            if active_userhash:
                data["userhash"] = active_userhash

            files = {
                "fileToUpload": (target_filename, file_bytes, mime_type)
            }

            try:
                response = session.post(
                    self.api_url,
                    data=data,
                    files=files,
                    timeout=120
                )

                response_text = response.text.strip() if response.text else ""

                # Check if Catbox returned a valid file URL
                url_match = re.search(r'https?://files\.catbox\.moe/[a-zA-Z0-9_\-\.]+', response_text)
                if url_match:
                    url = url_match.group(0)
                    if url.startswith("http://"):
                        url = "https://" + url[7:]
                    return url

                # Handle known fatal client errors (do not retry)
                if response.status_code == 412:
                    print(f"[CatboxService] Client rejected (412): {response_text}")
                    return None

                # If status 200 returned empty or unexpected body (e.g. transient timeout / proxy blip)
                print(
                    f"[CatboxService] Warning: Attempt {attempt}/{max_retries} returned status {response.status_code} "
                    f"with unexpected body: {repr(response_text[:100])}. Retrying in {attempt * 1.5:.1f}s..."
                )

            except (requests.exceptions.RequestException, ConnectionResetError) as e:
                print(
                    f"[CatboxService] Warning: Attempt {attempt}/{max_retries} failed with error: {e}. "
                    f"Retrying in {attempt * 1.5:.1f}s..."
                )

            if attempt < max_retries:
                time.sleep(attempt * 1.5)

        print(f"[CatboxService] Upload failed for '{target_filename}' after {max_retries} attempts.")
        return None

    def delete_files(self, files: Union[str, List[str]], userhash: Optional[str] = None) -> bool:
        """
        Delete files from Catbox (Requires valid userhash).
        API endpoint requires reqtype="deletefiles".

        Args:
            files: Single filename/URL or list of filenames/URLs.
            userhash: Account userhash.

        Returns:
            True if deletion succeeded, False otherwise.
        """
        active_userhash = userhash if userhash is not None else self.userhash
        if not active_userhash:
            print("[CatboxService] Error: userhash is required to delete files on Catbox.")
            return False

        if isinstance(files, str):
            file_list = [files]
        else:
            file_list = list(files)

        # Extract only basenames (e.g. 'https://files.catbox.moe/abc123.jpg' -> 'abc123.jpg')
        cleaned_filenames = []
        for f in file_list:
            cleaned = os.path.basename(f.strip())
            if cleaned:
                cleaned_filenames.append(cleaned)

        if not cleaned_filenames:
            return False

        data = {
            "reqtype": "deletefiles",
            "userhash": active_userhash,
            "files": " ".join(cleaned_filenames)
        }

        try:
            session = get_catbox_session()
            response = session.post(
                self.api_url,
                data=data,
                timeout=30
            )
            return response.status_code == 200 and (
                "Files successfully deleted" in response.text or "success" in response.text.lower()
            )
        except requests.exceptions.RequestException as e:
            print(f"[CatboxService] Delete error: {e}")
            return False

    def create_album(
        self,
        title: str,
        files: List[str],
        desc: Optional[str] = None,
        userhash: Optional[str] = None
    ) -> Optional[str]:
        """
        Create a dedicated Album on Catbox for a comic (Requires valid userhash).
        All files (cover, PDF, extracted pages) are grouped together under the album.

        Args:
            title: Title of the album (comic title).
            files: List of file URLs or filenames to include.
            desc: Optional album description.
            userhash: Optional userhash override.

        Returns:
            Album URL (e.g. 'https://catbox.moe/c/xxxxxx') or None on failure.
        """
        active_userhash = userhash if userhash is not None else self.userhash
        if not active_userhash:
            print("[CatboxService] Error: userhash is required to create an album on Catbox.")
            return None

        cleaned_filenames = []
        for f in files:
            cleaned = os.path.basename(f.strip().split('?')[0])
            if cleaned and cleaned not in cleaned_filenames:
                cleaned_filenames.append(cleaned)

        if not cleaned_filenames:
            print("[CatboxService] Error: No valid files provided for album creation.")
            return None

        data = {
            "reqtype": "createalbum",
            "userhash": active_userhash,
            "title": title.strip() or "Comic Album",
            "desc": desc.strip() if desc else f"ComicVault - {title.strip()}",
            "files": " ".join(cleaned_filenames)
        }

        try:
            session = get_catbox_session()
            response = session.post(self.api_url, data=data, timeout=30)
            text = response.text.strip()

            match = re.search(r'https?://catbox\.moe/c/[a-zA-Z0-9]+', text)
            if match:
                album_url = match.group(0)
                if album_url.startswith("http://"):
                    album_url = "https://" + album_url[7:]
                return album_url
            else:
                print(f"[CatboxService] Failed to create album. Status {response.status_code}: {text}")
                return None
        except Exception as e:
            print(f"[CatboxService] Exception creating album: {e}")
            return None

    def add_to_album(
        self,
        short_or_url: str,
        files: List[str],
        userhash: Optional[str] = None
    ) -> bool:
        """Add additional files to an existing Catbox album."""
        active_userhash = userhash if userhash is not None else self.userhash
        if not active_userhash:
            return False

        short = os.path.basename(short_or_url.strip().rstrip('/'))
        cleaned_filenames = [os.path.basename(f.strip().split('?')[0]) for f in files if f.strip()]
        if not cleaned_filenames:
            return False

        data = {
            "reqtype": "addtoalbum",
            "userhash": active_userhash,
            "short": short,
            "files": " ".join(cleaned_filenames)
        }
        try:
            session = get_catbox_session()
            response = session.post(self.api_url, data=data, timeout=30)
            return response.status_code == 200
        except Exception as e:
            print(f"[CatboxService] Add to album error: {e}")
            return False

    def delete_album(self, short_or_url: str, userhash: Optional[str] = None) -> bool:
        """Delete an album from Catbox."""
        active_userhash = userhash if userhash is not None else self.userhash
        if not active_userhash:
            return False

        short = os.path.basename(short_or_url.strip().rstrip('/'))
        data = {
            "reqtype": "deletealbum",
            "userhash": active_userhash,
            "short": short
        }
        try:
            session = get_catbox_session()
            response = session.post(self.api_url, data=data, timeout=30)
            return response.status_code == 200
        except Exception as e:
            print(f"[CatboxService] Delete album error: {e}")
            return False

    def test_connection(self, userhash: Optional[str] = None) -> Tuple[bool, str]:
        """
        Test connectivity to Catbox.moe API and validate userhash if provided.

        Returns:
            (success: bool, message: str)
        """
        active_userhash = userhash if userhash is not None else self.userhash
        active_userhash = active_userhash.strip() if active_userhash else ""

        # Minimal 1x1 transparent GIF (43 bytes)
        tiny_gif = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'

        url = self.upload_file(
            file_input=tiny_gif,
            filename="comicvault_ping.gif",
            userhash=active_userhash,
            max_retries=2
        )

        if url:
            # Clean up the test file if userhash is set
            if active_userhash:
                try:
                    self.delete_files(url, userhash=active_userhash)
                except Exception:
                    pass
            mode_desc = f"account userhash '{active_userhash[:4]}...'" if active_userhash else "anonymous mode"
            return True, f"Connection to Catbox.moe successful ({mode_desc})!"
        else:
            if active_userhash:
                return False, "Failed to upload to Catbox. Please check your internet connection or verify your userhash."
            return False, "Failed to reach Catbox.moe API. Please check your internet connection."
