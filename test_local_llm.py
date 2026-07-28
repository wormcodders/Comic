"""Test script to verify local LLM integration"""
import os
import sys

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from unified_uploader import UnifiedUploader
from vision_llm import ComicMetadataExtractor

def test_local_llm_detection():
    """Test that local LLM is properly detected"""
    print("=" * 60)
    print("Testing Local LLM Detection")
    print("=" * 60)
    
    # Test 1: Local LLM with localhost URL
    uploader1 = UnifiedUploader(
        ai_base_url='http://localhost:11434/v1/chat/completions',
        ai_model='llava',
        ai_api_key=None
    )
    print(f"\nTest 1 - Localhost URL:")
    print(f"  AI Base URL: {uploader1.ai_base_url}")
    print(f"  AI Model: {uploader1.ai_model}")
    print(f"  Use Local LLM: {uploader1.use_local_llm}")
    
    # Test 2: Cloud API with key
    uploader2 = UnifiedUploader(
        ai_base_url='https://api.openai.com/v1/chat/completions',
        ai_model='gpt-4-vision-preview',
        ai_api_key='sk-test-key'
    )
    print(f"\nTest 2 - Cloud API:")
    print(f"  AI Base URL: {uploader2.ai_base_url}")
    print(f"  AI Model: {uploader2.ai_model}")
    print(f"  AI API Key set: {bool(uploader2.ai_api_key)}")
    print(f"  Use Local LLM: {uploader2.use_local_llm}")
    
    # Test 3: Vision LLM Extractor with local LLM
    extractor = ComicMetadataExtractor(
        api_url='http://localhost:11434/v1/chat/completions',
        model='llava',
        use_local_llm=True
    )
    print(f"\nTest 3 - Vision LLM Extractor:")
    print(f"  API URL: {extractor.api_url}")
    print(f"  Model: {extractor.model}")
    print(f"  Use Local LLM: {extractor.use_local_llm}")
    print(f"  Demo Mode: {extractor.demo_mode}")
    print(f"  API Key: {extractor.api_key}")
    
    print("\n" + "=" * 60)
    print("Tests completed!")
    print("=" * 60)

if __name__ == "__main__":
    test_local_llm_detection()
