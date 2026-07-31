import sqlite3

def run():
    db = sqlite3.connect('data/delta_bt.sqlite')
    
    # Check if they exist first
    existing = db.execute("SELECT script_name FROM background_tasks").fetchall()
    existing_scripts = [r[0] for r in existing]
    
    if "stat_arb_scanner" not in existing_scripts:
        db.execute(
            "INSERT INTO background_tasks(name, description, interval_sec, script_name, params_json, status) VALUES (?, ?, ?, ?, ?, ?)",
            ("Stat Arb Scanner", "Calculates Z-Scores on correlated pairs and deploys mean reversion on divergences.", 300, "stat_arb_scanner", '{"base_lot_size": 1.0, "auto_deploy": false}', "running")
        )
        print("Inserted stat_arb_scanner")
        
    if "efficiency_evaluator" not in existing_scripts:
        db.execute(
            "INSERT INTO background_tasks(name, description, interval_sec, script_name, params_json, status) VALUES (?, ?, ?, ?, ?, ?)",
            ("Efficiency Evaluator", "Analyzes historical trades to measure the impact of institutional risk-management features.", 3600, "efficiency_evaluator", "{}", "running")
        )
        print("Inserted efficiency_evaluator")
        
    db.commit()

if __name__ == "__main__":
    run()
