from fastapi.testclient import TestClient
from delta_bt.server import create_app

app = create_app("/home/manoj/delta-cli/data/delta_bt.sqlite")
client = TestClient(app)

response = client.post("/api/tasks/106/delete")
print("Status Code:", response.status_code)
print("Response:", response.text)
