"""Content validation and bounded rendering for untrusted uploads."""

import io
import math
import os
import warnings

from PIL import Image
import pymupdf


MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_PDF_PAGES = 500


def read_limited(stream, limit=MAX_UPLOAD_BYTES):
    if isinstance(stream, (bytes, bytearray)):
        data = bytes(stream)
    elif hasattr(stream, 'read'):
        try:
            stream.seek(0)
        except (AttributeError, OSError, io.UnsupportedOperation):
            pass
        data = stream.read(limit + 1)
    else:
        raise ValueError('A binary file is required')
    if not isinstance(data, bytes) or not data:
        raise ValueError('The uploaded file is empty or invalid')
    if len(data) > limit:
        raise ValueError('The uploaded file exceeds the size limit')
    return data


def validate_pdf(data, max_pages=MAX_PDF_PAGES):
    if not data.lstrip()[:8].startswith(b'%PDF-'):
        raise ValueError('A valid PDF file is required')
    try:
        with pymupdf.open(stream=data, filetype='pdf') as document:
            if document.is_encrypted or not 1 <= document.page_count <= max_pages:
                raise ValueError(f'The PDF must be unencrypted and contain between 1 and {max_pages} pages')
    except (RuntimeError, pymupdf.FileDataError) as error:
        raise ValueError('The PDF could not be read') from error
    return data


def validate_image(data, filename):
    extension = os.path.splitext(filename)[1].lower()
    formats = {'.jpg': 'JPEG', '.jpeg': 'JPEG', '.png': 'PNG', '.gif': 'GIF', '.webp': 'WEBP'}
    if extension not in formats:
        raise ValueError('A PNG, JPEG, GIF, or WebP image is required')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format != formats[extension] or image.width * image.height > 20_000_000:
                    raise ValueError('Invalid image format or dimensions')
                image.verify()
    except (OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError('The image could not be read safely') from error
    return data


def validate_upload(data, filename):
    if not isinstance(filename, str):
        raise ValueError('A filename is required')
    if filename.lower().endswith('.pdf'):
        return validate_pdf(data)
    return validate_image(data, filename)


def normalized_cover(data, filename):
    validate_image(data, filename)
    with Image.open(io.BytesIO(data)) as image:
        image.thumbnail((2000, 2000))
        converted = image.convert('RGB')
        result = io.BytesIO()
        converted.save(result, format='JPEG', quality=90)
    return result.getvalue()


def render_pdf_page(page, zoom=2.0):
    """Limit pixel allocation even when a small PDF specifies enormous pages."""
    width, height = page.rect.width, page.rect.height
    if not math.isfinite(width) or not math.isfinite(height) or width <= 0 or height <= 0:
        raise ValueError('Invalid PDF page dimensions')
    scale = min(zoom, 2500 / width, 2500 / height, math.sqrt(4_000_000 / (width * height)))
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError('Invalid PDF page dimensions')
    return page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
