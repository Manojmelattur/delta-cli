import asyncio
from delta_bt.server import create_app
from fastapi.testclient import TestClient

app = create_app("/home/manoj/delta-cli/data/delta_bt.sqlite")
with TestClient(app) as client:
    res = client.get("/api/deployments")
    if len(res.json()) > 0:
        print("Type of params_json:", type(res.json()[0].get("params_json")))
        print("Value of params_json:", repr(res.json()[0].get("params_json")))
