from delta_bt.store.db import list_deployments
deps = list_deployments("/home/manoj/delta-cli/data/delta_bt.sqlite")
if deps:
    print("Type of params_json:", type(deps[0].get("params_json")))
    print("Value of params_json:", repr(deps[0].get("params_json")))
