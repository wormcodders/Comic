"""Test script to verify unified uploader is working correctly."""

import os
import sys

# Add project to path
sys.path.insert(0, 'E:\\Comic')

# Test configuration
config = {
    'COMIC_UPLOAD_FOLDER': 'E:\\Comic\\static\\uploads\\comics',
    'COVER_UPLOAD_FOLDER': 'E:\\Comic\\static\\uploads\\covers',
    'AI_API_KEY': os.environ.get('AI_API_KEY', ''),
    'AI_MODEL': 'gpt-4-vision-preview'
}

print("Testing UnifiedUploader...")

# Check if AI_API_KEY is set
if not config['AI_API_KEY']:
    print("\nWARNING: AI_API_KEY is not set!")
    print("The Vision LLM analysis will not work without an API key.")
    print("\nTo fix this, set the AI_API_KEY environment variable:")
    print("   set AI_API_KEY=your_api_key_here")
else:
    print(f"\nAI_API_KEY is set (length: {len(config['AI_API_KEY'])})")

# Try to import and initialize
from unified_uploader import UnifiedUploader, create_uploader_from_config

try:
    uploader = create_uploader_from_config(config)
    print(f"\nUnifiedUploader initialized successfully")
    print(f"   Upload folder: {uploader.upload_folder}")
    print(f"   Covers folder: {uploader.covers_folder}")
    print(f"   AI Model: {uploader.ai_model}")
    print(f"   AI API Key set: {bool(uploader.ai_api_key)}")
    
    # Check folders exist
    if os.path.exists(uploader.upload_folder):
        print(f"   Upload folder exists: YES")
    else:
        print(f"   Upload folder does not exist: {uploader.upload_folder}")
    
    if os.path.exists(uploader.covers_folder):
        print(f"   Covers folder exists: YES")
    else:
        print(f"   Covers folder does not exist: {uploader.covers_folder}")
        
except Exception as e:
    print(f"\nError initializing UnifiedUploader: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*60)
print("Test complete.")
