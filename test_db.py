import sqlite3
db = sqlite3.connect('data/delta_bt.sqlite')
print("equity:", db.execute("PRAGMA table_info(equity)").fetchall())
print("trades:", db.execute("PRAGMA table_info(trades)").fetchall())
