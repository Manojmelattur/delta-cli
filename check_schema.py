import json
from delta_bt.server import create_app

app = create_app()
schema = app.openapi()
for path, methods in schema.get("paths", {}).items():
    if "/api/deployments/create" in path:
        print("Create Schema:")
        print(json.dumps(methods, indent=2))
