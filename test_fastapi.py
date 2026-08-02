from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.testclient import TestClient

app = FastAPI()

class DeployRequest(BaseModel):
    name: str

@app.post("/api/create")
def create(req: DeployRequest):
    return {"ok": True}

client = TestClient(app)
res = client.post("/api/create", json={"name": "test"})
print(res.status_code, res.json())
