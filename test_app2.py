from app import app

print("Import OK")
print(f"App name: {app.name}")

# Test with a fresh database context
with app.app_context():
    from models import db
    db.create_all()
    print("Database created OK")

# List all routes
print("\nRegistered routes:")
for rule in app.url_map.iter_rules():
    if rule.endpoint != 'static':
        methods = ', '.join(sorted(rule.methods - {'OPTIONS', 'HEAD'}))
        print(f"  {rule.rule} [{methods}] -> {rule.endpoint}")

# Test home page
with app.test_client() as client:
    resp = client.get('/')
    print(f"\nGET / status: {resp.status_code}")
    if resp.status_code == 500:
        print(f"Error: {resp.data[:500]}")
