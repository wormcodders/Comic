
import os
import sys
import json
import requests
import uuid

# Add project root to sys.path
sys.path.insert(0, r'e:\Comic')

from app import create_app
from models import db, Setting

app = create_app()

with app.app_context():
    token = Setting.get('upfiles_token')
    endpoint = Setting.get('upfiles_endpoint', 'https://api.upfiles.com/upload')
    
    if token:
        filename = f"{uuid.uuid4().hex[:8]}_test.pdf"
        # 3MB file
        with open(filename, 'wb') as f:
            f.write(b'%PDF-1.4\n')
            f.write(b'0' * (3 * 1024 * 1024))
            f.write(b'%%EOF')
            
        try:
            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': '*/*',
                'Connection': 'keep-alive'
            })
            
            with open(filename, 'rb') as f:
                url = f"{endpoint}?token={token}"
                files = {'file': (filename, f, 'application/pdf')}
                
                print(f"Sending 3MB request to UpFiles with Session and Headers...")
                response = session.post(url, files=files, timeout=120)
                print(f"Status Code: {response.status_code}")
                print(f"Response: {response.text}")
                
        except Exception as e:
            print(f"Error: {e}")
        finally:
            if os.path.exists(filename):
                os.remove(filename)
    else:
        print("No token found in settings.")
