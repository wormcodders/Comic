"""
Vision LLM integration for automatic comic metadata extraction.
This module extracts title, author, artist, category, tags, and description
from comic cover images and PDFs using AI vision models.

Supports both cloud APIs (OpenAI, Anthropic, Gemini) and local LLMs (Ollama, etc.)
"""

import os
import base64
import json
import re
from typing import Dict, List, Optional, Tuple
import requests
from PIL import Image
import io
import tempfile

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False


class ComicMetadataExtractor:
    """
    Extract metadata from comic covers using Vision LLM APIs.
    Supports cloud APIs (OpenAI, Anthropic) and local LLMs (Ollama).
    """
    
    def __init__(self, 
                 api_key: str = None, 
                 api_url: str = None,
                 model: str = None,
                 use_local_llm: bool = False):
        """
        Initialize the metadata extractor.
        
        Args:
            api_key: API key for the vision LLM service (optional for local LLMs)
            api_url: Custom API URL (e.g., http://localhost:11434/v1/chat/completions for Ollama)
            model: Model name to use
            use_local_llm: Set to True if using a local LLM like Ollama (no API key required)
        """
        self.use_local_llm = use_local_llm or os.environ.get('USE_LOCAL_LLM', 'false').lower() == 'true'
        self.api_key = api_key or os.environ.get('VISION_API_KEY')
        
        # For local LLMs, default to Ollama's OpenAI-compatible endpoint
        default_url = 'http://localhost:11434/v1/chat/completions' if self.use_local_llm else 'https://api.openai.com/v1/chat/completions'
        self.api_url = api_url or os.environ.get('VISION_API_URL', default_url)
        
        # Default model based on provider
        default_model = 'llava' if self.use_local_llm else 'gpt-4o-mini'
        self.model = model or os.environ.get('VISION_MODEL', default_model)
        
        # Demo mode only if not using local LLM AND no API key
        self.demo_mode = not self.use_local_llm and not self.api_key
        
    def extract_from_image(self, image_path: str) -> Dict:
        """
        Extract metadata from a comic cover image.
        
        Args:
            image_path: Path to the cover image file
            
        Returns:
            Dictionary containing extracted metadata
        """
        try:
            # Load and encode image
            with open(image_path, 'rb') as f:
                image_data = f.read()
            
            base64_image = base64.b64encode(image_data).decode('utf-8')
            
            if self.demo_mode:
                return self._demo_extraction(image_path)
            
            return self._call_vision_api(base64_image)
            
        except Exception as e:
            return {'error': f'Failed to process image: {str(e)}'}
    
    def extract_from_pdf_first_page(self, pdf_path: str) -> Tuple[Dict, Optional[str]]:
        """
        Extract metadata from the first page of a PDF (cover page).
        Also extracts the first page as an image.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            Tuple of (metadata dict, cover_image_path or None)
        """
        try:
            if not PYMUPDF_AVAILABLE:
                return {'error': 'PyMuPDF not installed. Install with: pip install PyMuPDF'}, None
            
            # Open PDF and extract first page
            doc = fitz.open(pdf_path)
            if len(doc) == 0:
                return {'error': 'PDF has no pages'}, None
            
            # Get first page
            first_page = doc[0]
            
            # Render first page as image (high quality)
            mat = fitz.Matrix(2, 2)  # 2x zoom for better quality
            pix = first_page.get_pixmap(matrix=mat)
            
            # Convert to PIL Image
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))
            
            # Save temporarily
            temp_dir = tempfile.gettempdir()
            cover_path = os.path.join(temp_dir, f"comic_cover_{os.path.basename(pdf_path)}.png")
            img.save(cover_path, 'PNG', quality=95)
            
            # Extract metadata using the cover image
            metadata = self.extract_from_image(cover_path)
            
            doc.close()
            
            return metadata, cover_path
            
        except Exception as e:
            return {'error': f'Failed to process PDF: {str(e)}'}, None
    
    def extract_from_pdf_bytes(self, pdf_bytes: bytes, filename: str = "comic.pdf") -> Tuple[Dict, Optional[bytes]]:
        """
        Extract metadata from PDF bytes (first page).
        Also returns the cover image as bytes.
        
        Args:
            pdf_bytes: PDF file as bytes
            filename: Original filename for reference
            
        Returns:
            Tuple of (metadata dict, cover_image_bytes or None)
        """
        try:
            if not PYMUPDF_AVAILABLE:
                return {'error': 'PyMuPDF not installed. Install with: pip install PyMuPDF'}, None
            
            # Save bytes to temp file
            temp_dir = tempfile.gettempdir()
            tmp_pdf_path = os.path.join(temp_dir, f"temp_{filename}")
            
            with open(tmp_pdf_path, 'wb') as f:
                f.write(pdf_bytes)
            
            try:
                # Open PDF and extract first page
                doc = fitz.open(tmp_pdf_path)
                if len(doc) == 0:
                    return {'error': 'PDF has no pages'}, None
                
                first_page = doc[0]
                
                # Render at higher resolution
                mat = fitz.Matrix(2, 2)
                pix = first_page.get_pixmap(matrix=mat)
                
                # Convert to PIL Image
                img_data = pix.tobytes("png")
                img = Image.open(io.BytesIO(img_data))
                
                # Convert to bytes
                img_buffer = io.BytesIO()
                img.save(img_buffer, format='PNG', quality=95)
                img_bytes = img_buffer.getvalue()
                
                # Save temporarily for analysis
                temp_cover_path = os.path.join(tempfile.gettempdir(), f"cover_{filename}.png")
                with open(temp_cover_path, 'wb') as f:
                    f.write(img_bytes)
                
                # Extract metadata
                metadata = self.extract_from_image(temp_cover_path)
                
                doc.close()
                
                return metadata, img_bytes
                
            finally:
                # Cleanup temp PDF
                if os.path.exists(tmp_pdf_path):
                    os.remove(tmp_pdf_path)
                    
        except Exception as e:
            return {'error': f'Failed to process PDF: {str(e)}'}, None
    
    def _call_vision_api(self, base64_image: str) -> Dict:
        """
        Call the Vision LLM API to extract metadata.
        Supports both cloud APIs and local LLMs (Ollama).
        
        Args:
            base64_image: Base64 encoded image data
            
        Returns:
            Dictionary containing extracted metadata
        """
        try:
            # Prepare headers - local LLMs don't require Authorization
            headers = {
                'Content-Type': 'application/json'
            }
            
            # Only add Authorization header if API key is provided
            if self.api_key:
                headers['Authorization'] = f'Bearer {self.api_key}'
            
            prompt = """Analyze this comic book cover image and extract the following information:

1. Title: The main title of the comic (MUST be extracted in the EXACT SAME LANGUAGE as written on the cover. Do not translate to English unless the original is English)
2. Episode: The episode number if visible. Extract as purely an integer (e.g., 12, 3, 5). Do not include words like 'Episode' or 'Vol'. If not visible, return null
3. Author: The writer/author name (if visible on cover). MUST be in English or transliterated/romanized to English.
4. Artist: The illustrator/artist name (if different from author and visible). MUST be in English or transliterated/romanized to English.
5. Category: The genre/category (e.g., Action, Romance, Fantasy, Sci-Fi, Horror, Comedy, Drama, Manga, Superhero)
6. Tags: 5-8 relevant keywords/tags that describe the content
7. Description: A compelling 2-3 sentence summary that would be good for SEO (150-160 characters). (MUST be written in the SAME LANGUAGE as the comic title)

Return ONLY a JSON object with these fields:
{
    "title": "string (in original language)",
    "episode": "integer or null",
    "author": "string or Unknown",
    "artist": "string or null",
    "category": "string",
    "tags": ["tag1", "tag2", ...],
    "description": "string (in original language)"
}"""
            
            # Prepare payload based on provider type
            if self.use_local_llm or 'ollama' in self.api_url.lower():
                # Ollama-specific payload format
                payload = {
                    'model': self.model,
                    'messages': [
                        {
                            'role': 'user',
                            'content': prompt,
                            'images': [base64_image]
                        }
                    ],
                    'stream': False
                }
            else:
                # Standard OpenAI-compatible format
                payload = {
                    'model': self.model,
                    'messages': [
                        {
                            'role': 'user',
                            'content': [
                                {'type': 'text', 'text': prompt},
                                {
                                    'type': 'image_url',
                                    'image_url': {
                                        'url': f'data:image/jpeg;base64,{base64_image}'
                                    }
                                }
                            ]
                        }
                    ],
                    'max_tokens': 500
                }
            
            response = requests.post(self.api_url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            
            result = response.json()
            
            # Handle different response formats
            if self.use_local_llm or 'ollama' in self.api_url.lower():
                # Ollama format
                content = result.get('message', {}).get('content', '')
            else:
                # Standard OpenAI format
                content = result.get('choices', [{}])[0].get('message', {}).get('content', '')
            
            # Extract JSON from response
            return self._parse_json_response(content)
            
        except requests.exceptions.RequestException as e:
            return {'error': f'API request failed: {str(e)}'}
        except Exception as e:
            return {'error': f'Failed to parse API response: {str(e)}'}
    
    def _parse_json_response(self, content: str) -> Dict:
        """Parse JSON from API response, handling various formats."""
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
            
            return {
                'error': 'Could not parse JSON from response',
                'raw_response': content
            }
    
    def _demo_extraction(self, image_path: str) -> Dict:
        """
        Demo mode: Simulate extraction based on filename.
        In production, this would call an actual Vision LLM API.
        """
        filename = os.path.basename(image_path).lower()
        
        # Mock extraction based on filename patterns
        if 'superman' in filename or 'super' in filename:
            return {
                'title': 'Superman: Man of Tomorrow',
                'author': 'Brian Michael Bendis',
                'artist': 'Ivan Reis',
                'category': 'Superhero',
                'tags': ['superman', 'dc comics', 'superhero', 'action', 'justice league', 'krypton'],
                'description': 'The Man of Steel faces his greatest challenge yet as new threats emerge from the shadows of Metropolis.'
            }
        elif 'batman' in filename or 'bat' in filename:
            return {
                'title': 'Batman: The Dark Knight Returns',
                'author': 'Frank Miller',
                'artist': 'Frank Miller',
                'category': 'Superhero',
                'tags': ['batman', 'dc comics', 'dark knight', 'gotham', 'detective', 'noir'],
                'description': 'An aging Bruce Wayne returns from retirement to fight crime in a Gotham City that has forgotten what justice means.'
            }
        elif 'spider' in filename or 'spiderman' in filename:
            return {
                'title': 'The Amazing Spider-Man',
                'author': 'Stan Lee',
                'artist': 'Steve Ditko',
                'category': 'Superhero',
                'tags': ['spider-man', 'marvel', 'superhero', 'new york', 'web-slinger', 'peter parker'],
                'description': 'Your friendly neighborhood Spider-Man swings into action, balancing superhero duties with Peter Parker\'s personal life.'
            }
        elif 'x-men' in filename or 'xmen' in filename:
            return {
                'title': 'X-Men: Days of Future Past',
                'author': 'Chris Claremont',
                'artist': 'John Byrne',
                'category': 'Superhero',
                'tags': ['x-men', 'marvel', 'mutants', 'wolverine', 'future', 'dystopia'],
                'description': 'The X-Men race against time to prevent a dark future where mutants are hunted to extinction.'
            }
        elif 'avengers' in filename:
            return {
                'title': 'The Avengers',
                'author': 'Stan Lee',
                'artist': 'Jack Kirby',
                'category': 'Superhero',
                'tags': ['avengers', 'marvel', 'superhero team', 'action', 'adventure', 'earth\'s mightiest'],
                'description': 'Earth\'s mightiest heroes assemble to face threats no single hero can withstand.'
            }
        elif 'one piece' in filename or 'onepiece' in filename:
            return {
                'title': 'One Piece: Romance Dawn',
                'author': 'Eiichiro Oda',
                'artist': 'Eiichiro Oda',
                'category': 'Manga',
                'tags': ['manga', 'pirates', 'devil fruit', 'adventure', 'friendship', 'grand line'],
                'description': 'Monkey D. Luffy and his pirate crew search for the legendary One Piece treasure in this epic adventure manga.'
            }
        else:
            return {
                'title': 'Unknown Comic',
                'author': 'Unknown Author',
                'artist': None,
                'category': 'Comics',
                'tags': ['comic', 'graphic novel', 'adventure'],
                'description': 'An exciting comic book adventure with compelling characters and stunning artwork.'
            }


def optimize_description_for_seo(description: str, max_length: int = 160) -> str:
    """
    Optimize a description for SEO.
    
    Args:
        description: Original description
        max_length: Maximum length for meta description
        
    Returns:
        SEO-optimized description
    """
    # Clean up the description
    optimized = description.strip()
    
    # Remove extra whitespace
    optimized = ' '.join(optimized.split())
    
    # Truncate if too long
    if len(optimized) > max_length:
        optimized = optimized[:max_length-3].rsplit(' ', 1)[0] + '...'
    
    return optimized


def generate_meta_tags(title: str, description: str, tags: List[str], cover_url: str = None) -> Dict:
    """
    Generate SEO meta tags for a comic.
    
    Args:
        title: Comic title
        description: Comic description
        tags: List of tags
        cover_url: URL to cover image
        
    Returns:
        Dictionary of meta tags
    """
    seo_description = optimize_description_for_seo(description)
    
    meta_tags = {
        'title': title,
        'description': seo_description,
        'keywords': ', '.join(tags),
        'og_title': title,
        'og_description': seo_description,
        'twitter_title': title,
        'twitter_description': seo_description,
    }
    
    if cover_url:
        meta_tags['og_image'] = cover_url
        meta_tags['twitter_image'] = cover_url
    
    return meta_tags


def main():
    """Command line interface for testing the extractor"""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python vision_llm.py <image_path_or_pdf_path>")
        print("Example: python vision_llm.py comic_cover.jpg")
        print("Example: python vision_llm.py comic.pdf")
        return
    
    file_path = sys.argv[1]
    
    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' not found")
        return
    
    extractor = ComicMetadataExtractor()
    
    # Determine file type and extract accordingly
    if file_path.lower().endswith('.pdf'):
        print("Extracting from PDF first page...")
        result, cover_path = extractor.extract_from_pdf_first_page(file_path)
        if cover_path:
            print(f"Cover image saved to: {cover_path}")
    else:
        print("Extracting from image...")
        result = extractor.extract_from_image(file_path)
    
    # Print results
    print("\n" + "="*50)
    print("EXTRACTED METADATA:")
    print("="*50)
    
    if 'error' in result:
        print(f"Error: {result['error']}")
    else:
        print(f"Title: {result.get('title', 'N/A')}")
        print(f"Author: {result.get('author', 'N/A')}")
        print(f"Artist: {result.get('artist', 'N/A')}")
        print(f"Category: {result.get('category', 'N/A')}")
        print(f"Description: {result.get('description', 'N/A')}")
        print(f"Tags: {', '.join(result.get('tags', []))}")
        
        # Show SEO optimization
        if 'description' in result:
            seo_desc = optimize_description_for_seo(result['description'])
            print(f"\nSEO Optimized Description ({len(seo_desc)} chars):")
            print(seo_desc)
    
    print("="*50)


if __name__ == "__main__":
    main()
