from delta_bt.store.db import connect
db_path = "/home/manoj/delta-cli/data/delta_bt.sqlite"
with connect(db_path=db_path) as conn:
    cur = conn.execute("PRAGMA table_info(background_tasks);")
    for row in cur.fetchall():
        print(dict(row))
