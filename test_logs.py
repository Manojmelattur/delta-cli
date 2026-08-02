from delta_bt.store.db import connect
with connect("/home/manoj/delta-cli/data/delta_bt.sqlite") as conn:
    cur = conn.execute("SELECT * FROM task_logs ORDER BY id DESC LIMIT 10")
    for row in cur.fetchall():
        print(dict(row))
