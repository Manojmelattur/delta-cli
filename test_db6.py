from delta_bt.store.db import connect
db_path = "/home/manoj/delta-cli/data/delta_bt.sqlite"
with connect(db_path=db_path) as conn:
    cur = conn.execute("SELECT id, name, last_run_at, status FROM background_tasks LIMIT 5")
    for row in cur.fetchall():
        print(dict(row))
