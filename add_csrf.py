import os
import re

directory = 'e:/Comic/templates'
csrf_input = '\n    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>'

count = 0
for root, _, files in os.walk(directory):
    for file in files:
        if file.endswith('.html'):
            filepath = os.path.join(root, file)
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Find all forms with method='POST' (case insensitive)
            new_content = re.sub(
                r'(<form[^>]*method=[\'\"]POST[\'\"][^>]*>)',
                r'\g<1>' + csrf_input,
                content,
                flags=re.IGNORECASE
            )
            
            if new_content != content:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                count += 1

print(f'Updated {count} files with CSRF tokens.')
