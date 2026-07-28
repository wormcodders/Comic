import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from models import User

app.config['TESTING'] = True
app.config['PROPAGATE_EXCEPTIONS'] = True

with app.app_context():
    user = User.query.filter_by(is_admin=True).first()
    
with app.test_client() as client:
    if user:
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)
            sess['_fresh'] = True
        
        try:
            response = client.get('/')
            print(f"Status Code: {response.status_code}")
        except Exception as e:
            import traceback
            traceback.print_exc()
    else:
        print("No admin user found")
