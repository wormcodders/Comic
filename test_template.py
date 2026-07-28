import sys
sys.path.insert(0, r'E:\Comic')

from app import app

with app.app_context():
    from flask import render_template_string
    # Test that the template can be loaded
    try:
        from jinja2 import Environment, FileSystemLoader
        env = Environment(loader=FileSystemLoader(r'E:\Comic\templates'))
        template = env.get_template('library.html')
        print("Template loaded successfully!")
        
        # Create a mock pagination object
        class MockPagination:
            total = 5
            page = 1
            pages = 1
            items = []
            
        html = template.render(comics=MockPagination(), current_user=None, request=None)
        print("Template rendered successfully!")
        print("Fix verified!")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
