import re
with open("delta_bt/cli.py", "r") as f:
    text = f.read()
matches = re.finditer(r"def _add_backtest_args", text)
for m in matches:
    print(text[m.start():m.start()+2000])
