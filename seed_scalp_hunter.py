import sqlite3

def run():
    db = sqlite3.connect('data/delta_bt.sqlite')
    
    # Check if they exist first
    existing = db.execute("SELECT script_name FROM background_tasks").fetchall()
    existing_scripts = [r[0] for r in existing]
    
    if "scalp_hunter" not in existing_scripts:
        db.execute(
            "INSERT INTO background_tasks(name, description, interval_sec, script_name, params_json, status) VALUES (?, ?, ?, ?, ?, ?)",
            ("High-Frequency Scalp Hunter", "Scans 1m charts for extreme RSI divergences (<25 or >75) and a reversal candle, and instantly deploys tight scalp bots.", 60, "scalp_hunter", '{"base_lot_size": 1.0, "auto_deploy": false}', "running")
        )
        print("Inserted scalp_hunter")
        
    db.commit()

if __name__ == "__main__":
    run()
