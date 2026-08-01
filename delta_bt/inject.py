import re
with open("delta_bt/server.py", "r") as f:
    content = f.read()

if "add_pnl_routes" not in content:
    content = "from delta_bt.add_pnl_routes import add_pnl_routes\n" + content
    content = content.replace("app = FastAPI(", "app = FastAPI(\nadd_pnl_routes(app)\n", 1)
    
    with open("delta_bt/server.py", "w") as f:
        f.write(content)
