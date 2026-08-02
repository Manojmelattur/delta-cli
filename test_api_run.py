from delta_bt.server import api_run_summary
try:
    print(api_run_summary("backtest_20260731_143539"))
except Exception as e:
    import traceback
    traceback.print_exc()
