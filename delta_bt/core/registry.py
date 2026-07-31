"""Auto-discover Strategy subclasses under delta_bt/strategies/."""
from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Dict, Type

from . import strategy as _strategy_mod
from .strategy import Strategy


def discover_strategies() -> Dict[str, Type[Strategy]]:
    import delta_bt.strategies as pkg

    found: Dict[str, Type[Strategy]] = {}
    for _, modname, _ in pkgutil.iter_modules(pkg.__path__):
        mod = importlib.import_module(f"delta_bt.strategies.{modname}")
        for _, obj in inspect.getmembers(mod, inspect.isclass):
            if obj is Strategy or not issubclass(obj, Strategy):
                continue
            if obj.__module__ != mod.__name__:
                continue
            name = getattr(obj, "name", obj.__name__.lower())
            found[name] = obj
    return found


def load_strategy(name: str, params: dict) -> Strategy:
    reg = discover_strategies()
    if name not in reg:
        raise SystemExit(
            f"Unknown strategy '{name}'. Available: {sorted(reg)}"
        )
    return reg[name](params=params)
