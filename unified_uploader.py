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

# Try to import PyMuPDF for PDF processing
try:
    import fitz  # PyMuPDF
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
                 use_local_llm: bool = False):
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
        """
        self.upload_folder = upload_folder or os.path.join('static', 'uploads', 'comics')
        self.covers_folder = covers_folder or os.path.join('static', 'uploads', 'covers')
        self.upfiles_api_key = upfiles_api_key
        self.upfiles_endpoint = upfiles_endpoint
        self.ai_api_key = ai_api_key
        self.ai_model = ai_model
        self.ai_base_url = ai_base_url
        self.use_local_llm = use_local_llm
        
        # Ensure directories exist
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
            # Step 1: Validate file
            if not self._validate_file(filename, file_stream):
                result['errors'].append('Invalid file type or size')
                return result
            
            # Step 2: Save locally
            local_path = self._save_locally(file_stream, filename)
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
        """Validate file extension and size."""
        # Check extension
        ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
        if ext not in self.allowed_extensions:
            return False
        
        # Check size (if stream supports seeking)
        try:
            if hasattr(file_stream, 'seek') and hasattr(file_stream, 'tell'):
                file_stream.seek(0, 2)  # Seek to end
                size = file_stream.tell()
                file_stream.seek(0)  # Reset to beginning
                if size > self.max_file_size:
                    return False
        except:
            pass  # If we can't check size, continue anyway
        
        return True
    
    def _save_locally(self, file_stream, filename: str) -> Optional[str]:
        """Save file to local storage."""
        try:
            # Generate unique filename (use shorter prefix to avoid API issues with long names)
            safe_filename = secure_filename(filename)
            unique_name = f"{uuid.uuid4().hex[:8]}_{safe_filename}"
            filepath = os.path.join(self.upload_folder, unique_name)
            
            # Save file
            if hasattr(file_stream, 'read'):
                with open(filepath, 'wb') as f:
                    shutil.copyfileobj(file_stream, f)
            else:
                # Assume it's bytes
                with open(filepath, 'wb') as f:
                    f.write(file_stream)
            
            return filepath
        except Exception as e:
            print(f"Error saving file: {e}")
            return None
    
    def _extract_sample_pages(self, pdf_path: str, count: int = 3) -> List[str]:
        """Extract first few pages for AI context. Returns list of paths."""
        if not PYMUPDF_AVAILABLE:
            return []
        
        extracted_paths = []
        try:
            doc = fitz.open(pdf_path)
            if len(doc) == 0:
                return []
            
            base_name = os.path.splitext(os.path.basename(pdf_path))[0]
            
            for i in range(min(count, len(doc))):
                page = doc[i]
                mat = fitz.Matrix(1.5, 1.5) # Slightly lower res for AI speed
                pix = page.get_pixmap(matrix=mat)
                img_data = pix.tobytes("png")
                img = Image.open(io.BytesIO(img_data))
                
                page_filename = f"{base_name}_p{i}.png"
                page_path = os.path.join(self.covers_folder, page_filename)
                img.save(page_path, 'PNG')
                extracted_paths.append(page_path)
            
            doc.close()
            return extracted_paths
            
        except Exception as e:
            print(f"Error extracting sample pages: {e}")
            return extracted_paths

    
    def _analyze_with_vision_llm(self, image_paths: Union[str, List[str]]) -> Optional[Dict]:
        """Analyze images with Vision LLM to extract metadata."""
        if isinstance(image_paths, str):
            image_paths = [image_paths]
            
        # Skip if no AI configuration and not using local LLM
        if not self.use_local_llm and not self.ai_api_key:
            return None
        
        try:
            # Read and encode all images
            encoded_images = []
            for path in image_paths:
                with open(path, 'rb') as f:
                    encoded_images.append(base64.b64encode(f.read()).decode('utf-8'))
            
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
            response = requests.post(api_url, headers=headers, json=payload, timeout=timeout)
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
                print(f"Warning: Could not find content in LLM response: {result}")
                return None
                
            # Extract JSON from response
            return self._parse_llm_response(content)
            
        except Exception as e:
            print(f"Vision LLM API request failed: {str(e)}")
            return None
    
    def _parse_llm_response(self, content: str) -> Optional[Dict]:
        """Parse JSON from LLM response."""
        try:
            # Try direct JSON parsing
            return json.loads(content)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks
            json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group(1).strip())
                except json.JSONDecodeError:
                    pass
            
            # Try to extract JSON from plain text
            json_match = re.search(r'\{[^}]*"title"[^}]*\}', content, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group(0))
                except json.JSONDecodeError:
                    pass
            
            return None
    
    def _upload_to_upfiles(self, file_path: str) -> Dict:
        """Upload file to upfiles.com."""
        if not self.upfiles_api_key:
            return {'success': False, 'message': 'No upfiles API key configured'}
        
        max_retries = 3
        retry_delay = 2 # seconds
        
        for attempt in range(max_retries):
            try:
                with open(file_path, 'rb') as f:
                    files = {
                        'token': (None, self.upfiles_api_key),
                        'file': (os.path.basename(file_path), f, 'application/pdf')
                    }
                    
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                    }
                    
                    response = requests.post(
                        self.upfiles_endpoint,
                        files=files,
                        headers=headers,
                        timeout=300
                    )
                    response.raise_for_status()
                    
                    result = response.json()
                    
                    if result.get('status') == 'success':
                        return {
                            'success': True,
                            'url': result.get('url'),
                            'file_id': result.get('file_id')
                        }
                    else:
                        # API error, don't necessarily retry unless it's a network thing
                        return {
                            'success': False,
                            'message': result.get('message', 'Unknown error from upfiles')
                        }
                        
            except (requests.exceptions.RequestException, ConnectionResetError) as e:
                if attempt < max_retries - 1:
                    import time
                    time.sleep(retry_delay)
                    continue
                return {'success': False, 'message': f'Upload failed after {max_retries} attempts: {str(e)}'}
            except Exception as e:
                return {'success': False, 'message': f'Error: {str(e)}'}
        
        return {'success': False, 'message': 'Maximum retries exceeded'}

    def extract_pages(self, pdf_path: str, comic_id: str) -> List[str]:
        """
        Extract all pages of a PDF as images.
        """
        try:
            import fitz  # PyMuPDF
            
            # Create a directory for this comic's pages
            # self.covers_folder is static/uploads/covers
            base_pages_dir = os.path.join(os.path.dirname(self.covers_folder), 'pages')
            comic_pages_dir = os.path.join(base_pages_dir, str(comic_id))
            os.makedirs(comic_pages_dir, exist_ok=True)
            
            doc = fitz.open(pdf_path)
            image_urls = []
            
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                # Render page to image (2.0 zoom for better quality)
                zoom = 2.0
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat)
                
                image_name = f"page_{page_num + 1:03d}.jpg"
                image_path = os.path.join(comic_pages_dir, image_name)
                
                # Save as JPEG
                pix.save(image_path)
                
                # Relative URL from static
                rel_url = f"/static/uploads/pages/{comic_id}/{image_name}"
                image_urls.append(rel_url)
                
            doc.close()
            return image_urls
        except Exception as e:
            print(f"Extraction error: {str(e)}")
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
        use_local_llm=config.get('USE_LOCAL_LLM', False)
    )
