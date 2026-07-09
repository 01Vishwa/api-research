
with open('scripts/seed_verified_data.py', encoding='utf-8') as f:
    content = f.read()

# Fix invalid blocker values that should use enum-valid strings
content = content.replace('"blocker": "admin-approval"', '"blocker": "partner-approval-required"')

with open('scripts/seed_verified_data.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed')
