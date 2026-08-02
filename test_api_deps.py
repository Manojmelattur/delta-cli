import urllib.request
import json
try:
    req = urllib.request.Request("http://127.0.0.1:8000/api/deployments")
    with urllib.request.urlopen(req) as response:
        deps = json.loads(response.read().decode('utf-8'))
        if deps:
            print(deps[0])
        else:
            print("No deployments.")
except Exception as e:
    print(e)
