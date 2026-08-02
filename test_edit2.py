import requests
import json
headers = {"Host": "localhost", "Content-Type": "application/json"}
data = {"size": 1.0, "params": {}}
res = requests.post("http://127.0.0.1:8001/api/deployments/82/edit", json=data, headers=headers)
print(f"Status: {res.status_code}")
print(res.text)
