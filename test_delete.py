import asyncio
from delta_bt.server import create_app

app = create_app("/home/manoj/delta-cli/data/delta_bt.sqlite")

# Find the delete route
delete_route = None
for route in app.routes:
    if route.path == "/api/tasks/{task_id}/delete":
        delete_route = route
        break

if delete_route:
    try:
        # Since it's a sync function, we can just call it
        res = delete_route.endpoint(task_id=106)
        print("SUCCESS:", res)
    except Exception as e:
        import traceback
        traceback.print_exc()
else:
    print("Route not found")
