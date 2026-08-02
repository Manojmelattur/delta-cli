import urllib.request
import json
try:
    req = urllib.request.Request("http://127.0.0.1:37754/api/deployments")
    with urllib.request.urlopen(req) as response:
        deps = json.loads(response.read().decode('utf-8'))
        print(deps[:1])
except Exception as e:
    print(e)
