import requests

headers = {"Host": "localhost", "Content-Type": "application/json"}
res = requests.post("http://127.0.0.1:8000/api/deployments/82/edit", json={"size": 1.0, "params": {}}, headers=headers)
print(f"Status: {res.status_code}")
print(res.text)
