"""
Unified Uploader Module for ComicVault

This module provides a single, consolidated uploader that handles:
1. File storage (local)
2. Cover extraction (first page from PDF)
3. Vision LLM analysis (metadata extraction)
4. upfiles.com API upload (external hosting)

All operations are handled in a single workflow with proper error handling.
"""

import os
import base64
import json
import re
import requests
import tempfile
import shutil
from typing import Dict, List, Optional, Tuple, Any, Union
from pathlib import Path
from werkzeug.utils import secure_filename
from PIL import Image
import io
import uuid
from network_utils import safe_request, download_remote_file
from security_utils import is_safe_path, safe_join_path, sanitize_plain_text
from upload_utils import read_limited, validate_pdf, render_pdf_page, MAX_PDF_PAGES

# Try to import PyMuPDF for PDF processing
try:
    import pymupdf as fitz
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False


class UnifiedUploader:
    """
    Single uploader that handles all comic upload operations:
    - File validation and storage
    - Cover extraction from PDF
    - Vision LLM metadata extraction
    - upfiles.com API upload
    """
    
    def __init__(self, 
                 upload_folder: str = None,
                 covers_folder: str = None,
                 upfiles_api_key: str = None,
                 upfiles_endpoint: str = 'https://api.upfiles.com/upload',
                 ai_api_key: str = None,
                 ai_model: str = None,
                 ai_base_url: str = None,
                 use_local_llm: bool = False,
                 cloud_storage_enabled: bool = False,
                 catbox_userhash: str = None):
        """
        Initialize the unified uploader.
        
        Args:
            upload_folder: Local folder for storing PDFs
            covers_folder: Local folder for storing extracted covers
            upfiles_api_key: API key for upfiles.com
            upfiles_endpoint: upfiles.com API endpoint
            ai_api_key: API key for Vision LLM (optional for local LLMs)
            ai_model: AI model to use for vision analysis
            ai_base_url: Custom API base URL (e.g., http://localhost:11434/v1 for Ollama)
            use_local_llm: Set to True if using a local LLM like Ollama
            cloud_storage_enabled: Set to True to stream directly to Catbox.moe (zero local files)
            catbox_userhash: Optional account userhash for Catbox.moe
        """
        self.upload_folder = upload_folder or os.path.join('static', 'uploads', 'comics')
        self.covers_folder = covers_folder or os.path.join('static', 'uploads', 'covers')
        self.upfiles_api_key = upfiles_api_key
        self.upfiles_endpoint = upfiles_endpoint
        self.ai_api_key = ai_api_key
        self.ai_model = ai_model
        self.ai_base_url = ai_base_url
        self.use_local_llm = use_local_llm
        self.cloud_storage_enabled = cloud_storage_enabled
        self.catbox_userhash = catbox_userhash or ""
        
        # Ensure directories exist (for local mode fallback)
        os.makedirs(self.upload_folder, exist_ok=True)
        os.makedirs(self.covers_folder, exist_ok=True)
        
        # Allowed file types
        self.allowed_extensions = {'pdf'}
        self.max_file_size = 50 * 1024 * 1024  # 50MB
    
    def upload_comic(self, 
                     file_stream,
                     filename: str,
                     extract_metadata: bool = True,
                     upload_to_upfiles: bool = True) -> Dict[str, Any]:
        """
        Main upload method that handles the complete workflow.
        
        This is the SINGLE entry point for all comic uploads.
        It performs:
        1. File validation
        2. Local storage
        3. Cover extraction (first page)
        4. Vision LLM analysis (if enabled)
        5. upfiles.com upload (if enabled)
        
        Args:
            file_stream: File-like object or bytes
            filename: Original filename
            extract_metadata: Whether to extract metadata using Vision LLM
            upload_to_upfiles: Whether to upload to upfiles.com
            
        Returns:
            Dictionary with upload results including:
            - success: bool
            - local_path: str (path to saved file)
            - cover_path: str (path to extracted cover)
            - metadata: dict (extracted metadata)
            - upfiles_url: str (URL from upfiles)
            - errors: list (any non-critical errors)
        """
        result = {
            'success': False,
            'local_path': None,
            'cover_path': None,
            'cover_url': None,
            'metadata': None,
            'upfiles_url': None,
            'errors': []
        }
        
        try:
            # Validate actual bytes before saving, rendering, or contacting any host.
            try:
                pdf_bytes = read_limited(file_stream, self.max_file_size)
                if not self._validate_file(filename, pdf_bytes):
                    raise ValueError('A valid, unencrypted PDF within the size and page limits is required')
            except ValueError as error:
                result['validation_error'] = True
                result['errors'].append(str(error))
                return result

            # Check if direct cloud upload to Catbox is enabled
            if self.cloud_storage_enabled:
                from catbox_service import CatboxService
                catbox = CatboxService(userhash=self.catbox_userhash)
                
                base_name, ext = os.path.splitext(filename)
                clean_base = secure_filename(base_name)
                if not clean_base:
                    clean_base = "comic"
                clean_ext = ext.lower().strip() if ext else ".pdf"
                if not clean_ext.startswith('.'):
                    clean_ext = '.' + clean_ext
                safe_filename = f"{clean_base}{clean_ext}"
                unique_prefix = uuid.uuid4().hex[:8]
                pdf_cloud_name = f"{unique_prefix}_{clean_base}{clean_ext}"
                cover_cloud_name = f"cover_{unique_prefix}_{clean_base}.jpg"
                
                # Extract cover & sample pages directly in memory
                sample_bytes_list = []
                cover_bytes = None
                if PYMUPDF_AVAILABLE:
                    try:
                        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                        if len(doc) > 0:
                            # Render cover
                            mat = fitz.Matrix(1.5, 1.5)
                            cover_pix = render_pdf_page(doc[0], zoom=1.5)
                            cover_bytes = cover_pix.tobytes("jpeg")
                            sample_bytes_list.append(cover_bytes)
                            
                            # Render up to 2 more sample pages for vision LLM context
                            for i in range(1, min(3, len(doc))):
                                pix = render_pdf_page(doc[i], zoom=1.5)
                                sample_bytes_list.append(pix.tobytes("jpeg"))
                        doc.close()
                    except Exception as e:
                        result['errors'].append(f'In-memory sample extraction failed: {str(e)}')

                # 1. Upload Cover directly to Catbox
                if cover_bytes:
                    cover_catbox_url = catbox.upload_file(cover_bytes, filename=cover_cloud_name)
                    if cover_catbox_url:
                        result['cover_path'] = cover_catbox_url
                        result['cover_url'] = cover_catbox_url
                    else:
                        result['errors'].append('Failed to upload cover to Catbox')

                # 2. Upload Raw PDF directly to Catbox
                pdf_catbox_url = catbox.upload_file(pdf_bytes, filename=pdf_cloud_name)
                if pdf_catbox_url:
                    result['local_path'] = pdf_catbox_url  # holds the primary PDF reference URL
                else:
                    result['errors'].append('Failed to upload PDF to Catbox')

                # Store raw PDF bytes in result for immediate in-memory page extraction by caller
                result['pdf_bytes'] = pdf_bytes

                # 3. Vision LLM analysis using in-memory sample images
                if extract_metadata and sample_bytes_list:
                    metadata = self._analyze_with_vision_llm(sample_bytes_list)
                    if metadata:
                        result['metadata'] = metadata
                    else:
                        result['errors'].append('Vision LLM analysis failed (non-critical)')

                # 4. Upload to upfiles if requested
                if upload_to_upfiles:
                    upfiles_result = self._upload_to_upfiles(pdf_bytes, filename=safe_filename)
                    if upfiles_result.get('success'):
                        result['upfiles_url'] = upfiles_result.get('url')
                    else:
                        result['errors'].append(f"Upfiles upload failed: {upfiles_result.get('message', 'Unknown error')}")

                has_cloud_pdf = result['local_path'] is not None
                upfiles_ok = not upload_to_upfiles or result['upfiles_url'] is not None
                result['success'] = has_cloud_pdf and upfiles_ok
                return result

            # --- LOCAL DISK FLOW (When Cloud Storage is Disabled) ---
            # Step 2: Save locally
            local_path = self._save_locally(pdf_bytes, filename)
            if not local_path:
                result['errors'].append('Failed to save file locally')
                return result
            
            result['local_path'] = local_path
            
            # Step 3: Extract sample pages (cover + next 2 pages) for better AI context
            sample_paths = self._extract_sample_pages(local_path)
            if sample_paths:
                cover_path = sample_paths[0] # First one is cover
                result['cover_path'] = os.path.basename(cover_path)
                result['cover_url'] = f"/static/uploads/covers/{os.path.basename(cover_path)}"
            else:
                result['errors'].append('Sample extraction failed (non-critical)')
                cover_path = None
            
            # Step 4: Vision LLM analysis (if enabled)
            if extract_metadata and sample_paths:
                metadata = self._analyze_with_vision_llm(sample_paths)
                if metadata:
                    result['metadata'] = metadata
                else:
                    result['errors'].append('Vision LLM analysis failed (non-critical)')
            
            # Step 5: Upload to upfiles.com (if enabled)
            if upload_to_upfiles:
                upfiles_result = self._upload_to_upfiles(local_path)
                if upfiles_result.get('success'):
                    result['upfiles_url'] = upfiles_result.get('url')
                else:
                    result['errors'].append(f"Upfiles upload failed: {upfiles_result.get('message', 'Unknown error')}")
            
            # Final success determination: 
            # 1. We must have at least a local path
            # 2. If upfiles was requested, it must have succeeded
            has_local = result['local_path'] is not None
            upfiles_ok = not upload_to_upfiles or result['upfiles_url'] is not None
            
            result['success'] = has_local and upfiles_ok
            
        except Exception as e:
            result['errors'].append(f'Upload error: {str(e)}')
        
        return result
    
    def _validate_file(self, filename: str, file_stream) -> bool:
        """Check content and limits even for raw bytes and non-seekable streams."""
        if not isinstance(filename, str) or not filename.lower().endswith('.pdf'):
            return False
        try:
            validate_pdf(read_limited(file_stream, self.max_file_size))
            return True
        except (ValueError, OSError):
            return False
    
    def _save_locally(self, file_stream, filename: str) -> Optional[str]:
        """Save a validated PDF under an unpredictable, non-overwriting name."""
        try:
            base = secure_filename(os.path.splitext(filename)[0])[:150] or 'comic'
            path = safe_join_path(self.upload_folder, f'{uuid.uuid4().hex}_{base}.pdf')
            if not path:
                return None
            with open(path, 'xb') as target:
                target.write(read_limited(file_stream, self.max_file_size))
            return path
        except (ValueError, OSError):
            return None
    
    def _extract_sample_pages(self, pdf_path: str, count: int = 3) -> List[str]:
        """Render bounded sample images and always close the PDF."""
        paths = []
        try:
            if not is_safe_path(self.upload_folder, pdf_path):
                return []
            with fitz.open(pdf_path) as document:
                if not 1 <= document.page_count <= MAX_PDF_PAGES:
                    return []
                base = os.path.splitext(os.path.basename(pdf_path))[0]
                for index in range(min(count, document.page_count)):
                    path = safe_join_path(self.covers_folder, f'{base}_p{index}.png')
                    if not path:
                        return []
                    render_pdf_page(document[index], zoom=1.5).save(path)
                    paths.append(path)
        except (ValueError, RuntimeError, OSError):
            return []
        return paths

    
    def _analyze_with_vision_llm(self, image_inputs: Union[str, bytes, io.BytesIO, List[Any]]) -> Optional[Dict]:
        """Analyze images with Vision LLM to extract metadata."""
        if not isinstance(image_inputs, list):
            image_inputs = [image_inputs]
            
        # Skip if no AI configuration and not using local LLM
        if not self.use_local_llm and not self.ai_api_key:
            return None
        
        try:
            # Read and encode all images
            encoded_images = []
            for item in image_inputs:
                if isinstance(item, str):
                    with open(item, 'rb') as f:
                        encoded_images.append(base64.b64encode(f.read()).decode('utf-8'))
                elif isinstance(item, (bytes, bytearray)):
                    encoded_images.append(base64.b64encode(bytes(item)).decode('utf-8'))
                elif hasattr(item, 'read'):
                    if hasattr(item, 'seek'):
                        item.seek(0)
                    encoded_images.append(base64.b64encode(item.read()).decode('utf-8'))
            
            prompt = """Analyze these comic book images (cover and initial pages) and extract detailed metadata. 

For the 'description' field, you MUST follow these rules:
1. Length: 80 to 100 words precisely.
2. Content: Craft a compelling, imaginative, and SEO-optimized story blurb. 
3. Style: Do not just describe the art. Use the title and pages to build a hook.
4. Structure: End the description with an engaging narrative hook about what the main character is going to do next, leaving the reader wanting more.
5. SEO: Include relevant keywords naturally.

Return the result as a JSON object with these exact keys:
{
    "title": "the main comic title (MUST be extracted in the EXACT SAME LANGUAGE as written on the cover)",
    "episode": "the episode number if visible. Extract as purely an integer (e.g., 12, 3, 5). Do not include words like 'Episode' or 'Vol'. If not visible, return null",
    "author": "the writer/creator (MUST be in English or romanized/transliterated to English)",
    "artist": "the illustrator (MUST be in English or romanized/transliterated to English)",
    "category": "the primary genre (e.g., Action, Fantasy, Sci-Fi)",
    "language": "the detected language of the comic text (e.g., English, Japanese, French, Spanish)",
    "tags": ["list", "of", "6-8", "relevant", "keywords"],
    "description": "the 80-100 word SEO-friendly narrative blurb with a character hook (MUST be written in the SAME LANGUAGE as the comic title)"
}
"""
            
            # Determine API URL and model
            base_url = self.ai_base_url or 'https://api.openai.com/v1'
            
            # Ensure we have the full endpoint for chat completions
            if '/chat/completions' not in base_url:
                api_url = base_url.rstrip('/') + '/chat/completions'
            else:
                api_url = base_url
                
            model = self.ai_model or ('llava' if self.use_local_llm else 'gpt-4-vision-preview')
            
            # Prepare headers - local LLMs don't require Authorization
            headers = {
                'Content-Type': 'application/json'
            }
            
            # Only add Authorization header if API key is provided
            if self.ai_api_key:
                headers['Authorization'] = f'Bearer {self.ai_api_key}'
            
            # Prepare payload based on provider type
            if '/v1/chat/completions' in api_url:
                content_list = [{'type': 'text', 'text': prompt}]
                for img_b64 in encoded_images:
                    content_list.append({
                        'type': 'image_url',
                        'image_url': {
                            'url': f'data:image/png;base64,{img_b64}'
                        }
                    })
                
                payload = {
                    'model': model,
                    'messages': [
                        {
                            'role': 'user',
                            'content': content_list
                        }
                    ],
                    'max_tokens': 1000
                }
            else:
                # Fallback to simple format for native local APIs
                payload = {
                    'model': model,
                    'messages': [
                        {
                            'role': 'user',
                            'content': prompt,
                            'images': encoded_images
                        }
                    ],
                    'stream': False
                }
            
            # Make API call with longer timeout for local LLMs
            timeout = 120 if self.use_local_llm else 60
            response = safe_request('POST', api_url, headers=headers, json=payload, timeout=timeout,
                                    allow_local=self.use_local_llm, require_https=bool(self.ai_api_key) and not self.use_local_llm)
            response.raise_for_status()
            
            result = response.json()
            
            # Robust content extraction - try multiple common formats
            content = ""
            
            # 1. Standard OpenAI format: choices[0].message.content
            if 'choices' in result and len(result['choices']) > 0:
                choice = result['choices'][0]
                if 'message' in choice and 'content' in choice['message']:
                    content = choice['message']['content']
            
            # 2. Native Ollama format: message.content
            if not content and 'message' in result and 'content' in result['message']:
                content = result['message']['content']
                
            # 3. Direct content (some simple APIs): response or content
            if not content:
                content = result.get('content') or result.get('response') or ""
            
            if not content:
                print("Warning: The LLM did not return metadata text")
                return None
                
            # Extract JSON from response
            return self._parse_llm_response(content)
            
        except Exception as e:
            print(f"Vision LLM API request failed: {str(e)}")
            return None
    
    def _parse_llm_response(self, content: str) -> Optional[Dict]:
        """Accept a bounded metadata object, never arbitrary model output types."""
        if not isinstance(content, str) or len(content) > 65536:
            return None
        candidates = [content]
        match = re.search(r'```(?:json)?\s*(.*?)\s*```', content, re.DOTALL)
        if match:
            candidates.append(match.group(1))
        if '{' in content:
            candidates.append(content[content.index('{'):])
        parsed = None
        for candidate in candidates:
            try:
                value, _ = json.JSONDecoder().raw_decode(candidate.strip())
                if isinstance(value, dict):
                    parsed = value
                    break
            except (ValueError, TypeError):
                pass
        if parsed is None:
            return None
        limits = {'title': 200, 'author': 100, 'artist': 100, 'description': 10000, 'category': 50, 'language': 50}
        metadata = {key: sanitize_plain_text(parsed[key], limit) for key, limit in limits.items() if isinstance(parsed.get(key), str)}
        tags = parsed.get('tags')
        metadata['tags'] = list(dict.fromkeys(sanitize_plain_text(tag, 50) for tag in tags[:20] if isinstance(tag, str) and tag.strip())) if isinstance(tags, list) else []
        episode = parsed.get('episode')
        if type(episode) is int and 0 <= episode <= 1000000:
            metadata['episode'] = episode
        elif isinstance(episode, str) and episode.isascii() and episode.isdecimal() and len(episode) <= 7:
            metadata['episode'] = int(episode)
        else:
            metadata['episode'] = None
        return metadata
    
    def _upload_to_upfiles(self, file_input: Union[str, bytes], filename: Optional[str] = None) -> Dict:
        """Upload only validated PDFs using bounded, vetted network requests."""
        if not self.upfiles_api_key:
            return {'success': False, 'message': 'No UpFiles API key configured'}
        try:
            if isinstance(file_input, str):
                if file_input.startswith(('http://', 'https://')):
                    data = download_remote_file(file_input, max_bytes=self.max_file_size)
                    name = filename or os.path.basename(file_input.split('?')[0])
                else:
                    path = file_input if os.path.isabs(file_input) else safe_join_path(self.upload_folder, file_input)
                    if not path or not is_safe_path(self.upload_folder, path):
                        raise ValueError('Invalid local comic path')
                    with open(path, 'rb') as source:
                        data = read_limited(source, self.max_file_size)
                    name = filename or os.path.basename(path)
            else:
                data = read_limited(file_input, self.max_file_size)
                name = filename or 'comic.pdf'
            validate_pdf(data)
            name = secure_filename(name)[:180] or 'comic.pdf'
            if not name.lower().endswith('.pdf'):
                name += '.pdf'
            response = safe_request('POST', self.upfiles_endpoint,
                data={'token': self.upfiles_api_key}, files={'file': (name, data, 'application/pdf')},
                timeout=120, require_https=True)
            response.raise_for_status()
            result = response.json()
            if isinstance(result, dict) and result.get('status') == 'success' and isinstance(result.get('url'), str) and result['url'].startswith(('http://', 'https://')):
                return {'success': True, 'url': result['url'], 'file_id': result.get('file_id')}
            return {'success': False, 'message': 'The upload host did not return a file URL'}
        except ValueError:
            return {'success': False, 'message': 'Invalid file, destination, or upload response'}
        except (requests.RequestException, OSError):
            return {'success': False, 'message': 'The upload host could not be reached'}

    def extract_pages(self, pdf_input: Union[str, bytes, io.BytesIO], comic_id: str, upload_to_catbox: bool = False, catbox_userhash: Optional[str] = None) -> List[str]:
        """Extract a complete PDF with bounded download, page count, and pixels."""
        identifier = str(comic_id)
        if not identifier.isascii() or not identifier.isdecimal() or len(identifier) > 10 or int(identifier) < 1:
            return []
        try:
            if isinstance(pdf_input, str):
                if pdf_input.startswith(('http://', 'https://')):
                    data = download_remote_file(pdf_input, max_bytes=self.max_file_size)
                else:
                    path = pdf_input if os.path.isabs(pdf_input) else safe_join_path(self.upload_folder, pdf_input)
                    if not path or not is_safe_path(self.upload_folder, path):
                        return []
                    with open(path, 'rb') as source:
                        data = read_limited(source, self.max_file_size)
            else:
                data = read_limited(pdf_input, self.max_file_size)
            validate_pdf(data)
            urls = []
            with fitz.open(stream=data, filetype='pdf') as document:
                if upload_to_catbox:
                    from catbox_service import CatboxService
                    catbox = CatboxService(userhash=catbox_userhash if catbox_userhash is not None else self.catbox_userhash)
                    for index in range(document.page_count):
                        image = render_pdf_page(document[index]).tobytes('jpeg')
                        url = catbox.upload_file(image, filename=f'comic_{identifier}_page_{index + 1:03d}.jpg')
                        if not url:
                            return []  # Never persist a shifted or incomplete page sequence.
                        urls.append(url)
                else:
                    base_dir = os.path.join(os.path.dirname(self.covers_folder), 'pages')
                    target_dir = os.path.join(base_dir, identifier)
                    if not is_safe_path(base_dir, target_dir):
                        return []
                    os.makedirs(base_dir, exist_ok=True)
                    os.makedirs(target_dir, exist_ok=True)
                    marker = os.path.join(target_dir, '.complete')
                    if os.path.exists(marker):
                        os.remove(marker)
                    # Publish pages only after every page has rendered successfully.
                    with tempfile.TemporaryDirectory(prefix=f'comic_{identifier}_', dir=base_dir) as staging:
                        names = []
                        for index in range(document.page_count):
                            name = f'page_{index + 1:03d}.jpg'
                            render_pdf_page(document[index]).save(os.path.join(staging, name))
                            names.append(name)
                        for name in names:
                            target = safe_join_path(target_dir, name)
                            if not target:
                                return []
                            os.replace(os.path.join(staging, name), target)
                            urls.append(f'/static/uploads/pages/{identifier}/{name}')
                    with open(marker, 'w', encoding='ascii') as handle:
                        handle.write(str(document.page_count))
            return urls
        except (ValueError, RuntimeError, OSError, requests.RequestException):
            return []


def create_uploader_from_config(config: Dict) -> UnifiedUploader:
    """
    Create a UnifiedUploader instance from configuration dictionary.
    
    Args:
        config: Dictionary containing configuration keys:
            - UPLOAD_FOLDER
            - COVERS_FOLDER
            - UPFILES_API_KEY
            - UPFILES_ENDPOINT
            - AI_API_KEY
            - AI_MODEL
            - AI_BASE_URL
            - USE_LOCAL_LLM
            - CLOUD_STORAGE_ENABLED
            - CATBOX_USERHASH
            
    Returns:
        Configured UnifiedUploader instance
    """
    return UnifiedUploader(
        upload_folder=config.get('UPLOAD_FOLDER'),
        covers_folder=config.get('COVERS_FOLDER'),
        upfiles_api_key=config.get('UPFILES_API_KEY'),
        upfiles_endpoint=config.get('UPFILES_ENDPOINT', 'https://api.upfiles.com/upload'),
        ai_api_key=config.get('AI_API_KEY'),
        ai_model=config.get('AI_MODEL'),
        ai_base_url=config.get('AI_BASE_URL'),
        use_local_llm=config.get('USE_LOCAL_LLM', False),
        cloud_storage_enabled=config.get('CLOUD_STORAGE_ENABLED', False),
        catbox_userhash=config.get('CATBOX_USERHASH', '')
    )
