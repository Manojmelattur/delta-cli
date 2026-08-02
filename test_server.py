import urllib.request
import threading
import time
from delta_bt.server import serve

def run_server():
    serve(port=8001, db_path="/home/manoj/delta-cli/data/delta_bt.sqlite")

threading.Thread(target=run_server, daemon=True).start()
time.sleep(2)

try:
    req = urllib.request.Request("http://127.0.0.1:8001/api/tasks/95/delete", method="POST")
    with urllib.request.urlopen(req) as response:
        print("Status:", response.status)
        print("Body:", response.read().decode())
except urllib.error.HTTPError as e:
    print("Error Status:", e.code)
    print("Error Body:", e.read().decode())
