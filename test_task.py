import subprocess
import json

cmd = [
    "python", "-m", "delta_bt", "tasks", "add",
    "--name", "test_task",
    "--script", "test.py",
    "--interval", "900",
    "--desc", "test desc",
    "--params", "{}"
]

res = subprocess.run(cmd, capture_output=True, text=True)
print("Return code:", res.returncode)
print("Stdout:", res.stdout)
print("Stderr:", res.stderr)
