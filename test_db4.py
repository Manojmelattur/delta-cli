from delta_bt.store.db import connect
db_path = "/home/manoj/delta-cli/data/delta_bt.sqlite"
with connect(db_path=db_path) as conn:
    cur = conn.execute("SELECT id FROM background_tasks WHERE id=95")
    row = cur.fetchone()
    print("Task 95 exists:", row is not None)
