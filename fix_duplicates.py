#!/usr/bin/env python3
"""Fix duplicate sections in routes.py"""

with open('routes.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find all occurrences of 'Social Features API Routes'
occurrences = []
for i, line in enumerate(lines):
    if 'Social Features API Routes' in line:
        occurrences.append(i)

print(f'Found {len(occurrences)} occurrences at lines: {[i+1 for i in occurrences]}')

# The structure is:
# Line 1529: First header (good - keep)
# Line 1534: Second header (duplicate - remove from here to before last section)
# The last section starts at line 2239

# Find where the last good section starts
last_section_start = None
for i in range(len(lines) - 1, -1, -1):
    if 'Social Features API Routes' in lines[i]:
        last_section_start = i
        break

print(f'Last good section starts at line {last_section_start + 1}')

# Keep lines 0 to 1533 (before second header)
# Remove lines 1534 to last_section_start - 1
# Keep lines last_section_start to end

# But first, let's find where the second duplicate section actually starts
# and where it ends (before the last good section)

# Lines to keep: 0-1533 (inclusive) and last_section_start to end
# Lines to remove: 1534 to last_section_start - 1

new_lines = lines[:1534] + lines[last_section_start:]

with open('routes.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print(f'Removed lines 1535 to {last_section_start}')
print(f'New file has {len(new_lines)} lines')
print('Done!')
