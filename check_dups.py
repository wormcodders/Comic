import re

content = open('routes.py').read().split('\n')
funcs = {}

for i, line in enumerate(content, 1):
    match = re.match(r'def (\w+)\(', line)
    if match:
        func_name = match.group(1)
        if func_name not in funcs:
            funcs[func_name] = []
        funcs[func_name].append(i)

dups = {k: v for k, v in funcs.items() if len(v) > 1}

print('Duplicate functions:')
if dups:
    for name, lines in dups.items():
        print(f'  {name}: {len(lines)} occurrences at lines {lines}')
else:
    print('  None found')
