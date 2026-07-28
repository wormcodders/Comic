#!/usr/bin/env python3
"""Test script to verify local LLM configuration fix."""

import os
import sys

# Set environment variables for testing
os.environ['USE_LOCAL_LLM'] = 'true'
os.environ['AI_BASE_URL'] = 'http://localhost:11434/v1'

# Add the current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Test the config
from config import DevelopmentConfig

config = DevelopmentConfig()
print(f"USE_LOCAL_LLM from config: {config.USE_LOCAL_LLM}")
print(f"AI_BASE_URL from config: {config.AI_BASE_URL}")

# Test the uploader
from unified_uploader import create_uploader_from_config

uploader_config = {
    'UPLOAD_FOLDER': 'static/uploads/comics',
    'COVERS_FOLDER': 'static/uploads/covers',
    'AI_API_KEY': None,
    'AI_MODEL': 'llava',
    'AI_BASE_URL': 'http://localhost:11434/v1',
    'USE_LOCAL_LLM': True
}

uploader = create_uploader_from_config(uploader_config)
print(f"\nUploader use_local_llm: {uploader.use_local_llm}")
print(f"Uploader ai_api_key: {uploader.ai_api_key}")
print(f"Uploader ai_base_url: {uploader.ai_base_url}")

# Test the condition that was causing the skip
should_skip = not uploader.use_local_llm and not uploader.ai_api_key
print(f"\nShould skip Vision LLM analysis: {should_skip}")

if not should_skip:
    print("✅ SUCCESS: Vision LLM analysis will NOT be skipped!")
else:
    print("❌ FAILURE: Vision LLM analysis will be skipped!")
