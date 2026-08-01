with open("cli_original.py", "r") as f:
    orig = f.read()

def extract_func(func_name):
    start = orig.find(f"def {func_name}(")
    if start == -1: return ""
    end = orig.find("\ndef ", start + 10)
    if end == -1: return orig[start:]
    return orig[start:end] + "\n\n"

serve_func = extract_func("cmd_serve")
plot_func = extract_func("cmd_plot_diag")

with open("delta_bt/cli.py", "r") as f:
    cur = f.read()

cur = cur.replace("def cmd_rank_universe(a) -> int:", serve_func + plot_func + "def cmd_rank_universe(a) -> int:")

with open("delta_bt/cli.py", "w") as f:
    f.write(cur)

print("Restored cmd_serve and cmd_plot_diag")
