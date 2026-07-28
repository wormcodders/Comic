#!/usr/bin/env python
"""Script to remove duplicate get_comment_replies functions from routes.py"""

with open('E:\\Comic\\routes.py', 'r') as f:
    lines = f.readlines()

# Find lines with get_comment_replies function definitions
indices = []
for i, line in enumerate(lines):
    if 'def get_comment_replies(comment_id):' in line:
        indices.append(i)
        print(f"Found definition at line {i+1}")

print(f"\nTotal occurrences: {len(indices)}")

# We need to remove the first two, keep the third
# Get the line ranges for each function (including decorators)
def get_function_range(lines, def_line_idx):
    """Get the start (decorator) and end of a function"""
    # Find the decorator line (starts with @)
    start = def_line_idx
    while start > 0 and lines[start-1].strip().startswith('@'):
        start -= 1
    
    # Find the end of the function (next function/class or empty line followed by @/def/class)
    end = def_line_idx + 1
    indent_level = len(lines[def_line_idx]) - len(lines[def_line_idx].lstrip())
    
    while end < len(lines):
        line = lines[end]
        stripped = line.strip()
        
        # Check if we've reached the next function/class
        if stripped:
            current_indent = len(line) - len(line.lstrip())
            if current_indent <= indent_level and (stripped.startswith('def ') or stripped.startswith('class ') or stripped.startswith('@')):
                break
        end += 1
    
    return start, end

# Get ranges for first two functions
range1 = get_function_range(lines, indices[0])
range2 = get_function_range(lines, indices[1])

print(f"\nFirst function: lines {range1[0]+1} to {range1[1]}")
print(f"Second function: lines {range2[0]+1} to {range2[1]}")

# Remove lines in reverse order to preserve indices
to_remove = list(range(range2[0], range2[1])) + list(range(range1[0], range1[1]))
to_remove.sort(reverse=True)

for idx in to_remove:
    del lines[idx]

# Write back
with open('E:\\Comic\\routes.py', 'w') as f:
    f.writelines(lines)

print(f"\nRemoved {len(to_remove)} lines total")
print("File updated successfully!")
