import sqlite3
conn = sqlite3.connect("/home/manoj/delta-cli/data/delta_bt.sqlite")
cur = conn.execute("SELECT params_json FROM deployments LIMIT 1")
print(cur.fetchone())
