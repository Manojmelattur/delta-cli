import sys
import os

# Allow running as `python delta_bt` without `-m`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from delta_bt.cli import main

if __name__ == "__main__":
    main()
