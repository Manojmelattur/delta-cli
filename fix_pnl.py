import sys
import re

with open("delta_bt/pnl_analytics.py", "r") as f:
    content = f.read()

# I will just write a patch instead to avoid manual regex mess.
