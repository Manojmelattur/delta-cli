def test():
    from .store.db import connect
    print("Success")

try:
    test()
except Exception as e:
    import traceback
    traceback.print_exc()
