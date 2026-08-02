from delta_bt.store.db import connect
db_path = "/home/manoj/delta-cli/data/delta_bt.sqlite"
try:
    with connect(db_path=db_path) as conn:
        conn.execute("DELETE FROM background_tasks WHERE id=95")
        print("Success")
except Exception as e:
    import traceback
    traceback.print_exc()
