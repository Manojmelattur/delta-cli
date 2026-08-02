from delta_bt.store.db import connect
import time
db_path = "/home/manoj/delta-cli/data/delta_bt.sqlite"

try:
    with connect(db_path=db_path) as conn:
        conn.execute("DELETE FROM background_tasks WHERE id=?", (106,))
        print("Delete succeeded")
except Exception as e:
    import traceback
    traceback.print_exc()
