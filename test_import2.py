def test():
    from .store.db import connect
    print("Success")

__package__ = "delta_bt"
try:
    test()
except Exception as e:
    import traceback
    traceback.print_exc()
