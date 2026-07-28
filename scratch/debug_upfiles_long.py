
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
    
    print(f"Token: {token[:4]}...{token[-4:] if token else 'None'}")
    print(f"Endpoint: {endpoint}")
    
    if token:
        # Long filename with underscores
        filename = f"{uuid.uuid4().hex}_test_comic_file.pdf"
        with open(filename, 'wb') as f:
            f.write(b'%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n>>\nendobj\ntrailer\n<<\n/Root 1 0 R\n>>\n%%EOF')
            
        try:
            with open(filename, 'rb') as f:
                files = {'file': (filename, f, 'application/pdf')}
                data = {'token': token}
                
                print(f"Sending request to UpFiles with filename: {filename}")
                response = requests.post(endpoint, files=files, data=data, timeout=30)
                print(f"Status Code: {response.status_code}")
                print(f"Response: {response.text}")
                
        except Exception as e:
            print(f"Error: {e}")
        finally:
            if os.path.exists(filename):
                os.remove(filename)
    else:
        print("No token found in settings.")
