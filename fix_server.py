with open("delta_bt/server.py", "r") as f:
    lines = f.readlines()

new_lines = []
in_classes = False
class_lines = []
create_app_start = -1

for i, line in enumerate(lines):
    if line.startswith("def create_app"):
        create_app_start = i

    if line.startswith("    class BacktestRequest(BaseModel):"):
        in_classes = True
        
    if in_classes:
        if line.startswith("    @app.post(\"/api/backtest\")"):
            in_classes = False
            new_lines.append(line)
        else:
            # Dedent 4 spaces
            class_lines.append(line[4:] if line.startswith("    ") else line)
    else:
        new_lines.append(line)

# Insert the class_lines right before create_app
new_lines = new_lines[:create_app_start] + ["\n"] + class_lines + ["\n"] + new_lines[create_app_start:]

with open("delta_bt/server.py", "w") as f:
    f.writelines(new_lines)
