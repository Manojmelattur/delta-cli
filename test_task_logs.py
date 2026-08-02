import sqlite3
db=sqlite3.connect('data/delta_bt.sqlite')
print(db.execute('PRAGMA table_info(task_logs)').fetchall())
