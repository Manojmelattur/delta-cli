"""Live-order broker for demo/testnet paper trading."""
from __future__ import annotations

from typing import Optional

from ..core.types import Bar, Side, Signal
from ..data.delta_client import DeltaClient


class LiveBroker:
    """Places market orders on the Delta demo venue. Position state is tracked
    locally for reporting; canonical state lives at the exchange."""

    def __init__(self, client: DeltaClient, symbol: str, qty_contracts: int = 1):
        self.client = client
        self.symbol = symbol
        self.qty = qty_contracts
        self.product = client.get_product(symbol)
        self.product_id = int(self.product["id"])
        self._side: Optional[Side] = None

    def handle_signal(self, sig: Signal, bar: Bar):
        target = {Signal.BUY: Side.LONG, Signal.SELL: Side.SHORT,
                  Signal.FLAT: None, Signal.HOLD: self._side}.get(sig)
        if target == self._side:
            return
        # close existing
        if self._side is not None:
            close_side = "sell" if self._side == Side.LONG else "buy"
            self.client.place_order(self.product_id, self.qty, close_side)
            self._side = None
        # open new
        if target is not None:
            open_side = "buy" if target == Side.LONG else "sell"
            self.client.place_order(self.product_id, self.qty, open_side)
            self._side = target
