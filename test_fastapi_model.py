from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

app = FastAPI()

def add_routes(app):
    class TaskRequest(BaseModel):
        name: str
    
    @app.post("/test")
    def test_route(req: TaskRequest):
        return {"ok": True}

add_routes(app)

client = TestClient(app)
print(client.post("/test", json={"name": "foo"}).json())
