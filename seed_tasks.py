from delta_bt.store.db import connect
with connect() as conn:
    conn.execute("INSERT OR IGNORE INTO background_tasks(name, description, interval_sec, status, script_name) VALUES ('Emergency Monitor', 'Monitors live bot positions for extreme drawdowns and issues FLAT overrides', 900, 'running', 'emergency_monitor')")
    conn.execute("INSERT OR IGNORE INTO background_tasks(name, description, interval_sec, status, script_name) VALUES ('Daily Report', 'Generates a daily summary of bot activity', 86400, 'running', 'daily_report')")
print("Tasks seeded successfully via db.py connect()")
