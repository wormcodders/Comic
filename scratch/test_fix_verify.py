
import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, patch
from unified_uploader import UnifiedUploader

def test_config_resolution():
    # Mock settings that would be in the database
    mock_settings = {
        'llm_base_url': 'http://local-ollama:11434/v1',
        'llm_api_key': '',
        'llm_model': 'llama3-vision',
        'llm_use_local': '1',
        'upfiles_token': 'test-token'
    }
    
    # Simulate the logic in admin_unified_upload
    uploader = UnifiedUploader(
        upload_folder='test_uploads',
        covers_folder='test_covers'
    )
    
    print(f"Initial use_local_llm: {uploader.use_local_llm}")
    print(f"Initial ai_api_key: {uploader.ai_api_key}")
    
    # Apply database settings (simulating Setting.get)
    ai_api_key_db = mock_settings.get('llm_api_key')
    ai_model_db = mock_settings.get('llm_model')
    ai_base_url_db = mock_settings.get('llm_base_url')
    ai_use_local_db = mock_settings.get('llm_use_local')
    
    if ai_api_key_db is not None:
        uploader.ai_api_key = ai_api_key_db
    if ai_model_db:
        uploader.ai_model = ai_model_db
    if ai_base_url_db:
        uploader.ai_base_url = ai_base_url_db
        
    if ai_use_local_db == '1':
        uploader.use_local_llm = True
    elif ai_base_url_db:
        if 'localhost' in ai_base_url_db or '127.0.0.1' in ai_base_url_db or 'ollama' in ai_base_url_db.lower():
            uploader.use_local_llm = True
            
    print(f"Final use_local_llm: {uploader.use_local_llm}")
    print(f"Final ai_api_key: '{uploader.ai_api_key}'")
    print(f"Final ai_base_url: {uploader.ai_base_url}")
    
    # Verify the check in _analyze_with_vision_llm
    should_skip = not uploader.use_local_llm and not uploader.ai_api_key
    print(f"Would skip analysis? {should_skip}")
    
    assert uploader.use_local_llm is True
    assert should_skip is False
    print("Test passed!")

if __name__ == "__main__":
    test_config_resolution()
