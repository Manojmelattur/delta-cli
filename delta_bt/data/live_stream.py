"""Live bar builder — subscribes to Delta WebSocket ticker/trades and
aggregates into fixed-resolution OHLC bars for paper trading."""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from queue import Queue
from typing import Optional

try:
    import websocket  # websocket-client
except ImportError:  # deferred until paper trading is actually invoked
    websocket = None  # type: ignore

from ..core.types import Bar


_RES_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "1d": 86400,
}


class LiveBarStream:
    """Subscribes to `v2/ticker` for a symbol and emits closed OHLC bars.

    Usage:
        stream = LiveBarStream(ws_url, "BTCUSD", "1m")
        stream.start()
        for bar in stream.bars():   # blocking generator
            ...
    """

    def __init__(self, ws_url: str, symbol: str, resolution: str):
        self.ws_url = ws_url
        self.symbol = symbol
        self.resolution = resolution
        self.bucket = _RES_SECONDS.get(resolution)
        if not self.bucket:
            raise ValueError(f"Unsupported resolution: {resolution}")
        self._q: "Queue[Bar]" = Queue()
        self._ws: Optional[websocket.WebSocketApp] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

        # current in-progress bar
        self._cur_start: Optional[int] = None
        self._o = self._h = self._l = self._c = 0.0
        self._v = 0.0

    # ------------------------------------------------------------------
    def _bucket_start(self, ts: float) -> int:
        return int(ts - (ts % self.bucket))

    def _emit_if_new_bucket(self, ts: float, price: float, size: float = 0.0):
        b_start = self._bucket_start(ts)
        if self._cur_start is None:
            self._cur_start = b_start
            self._o = self._h = self._l = self._c = price
            self._v = size
            print(f"[ws] first tick received  price={price}  "
                  f"bucket_ends_in={int(b_start + self.bucket - ts)}s")
            return
        if b_start != self._cur_start:
            # emit closed bar
            bar = Bar(
                ts=datetime.fromtimestamp(self._cur_start + self.bucket, tz=timezone.utc),
                open=self._o, high=self._h, low=self._l, close=self._c,
                volume=self._v, symbol=self.symbol, resolution=self.resolution,
            )
            self._q.put(bar)
            self._cur_start = b_start
            self._o = self._h = self._l = self._c = price
            self._v = size
        else:
            self._h = max(self._h, price)
            self._l = min(self._l, price)
            self._c = price
            self._v += size

    # ------------------------------------------------------------------
    def _on_open(self, ws):
        print(f"[ws] connected  {self.ws_url}  subscribing {self.symbol} v2/ticker")
        sub = {
            "type": "subscribe",
            "payload": {
                "channels": [
                    {"name": "v2/ticker", "symbols": [self.symbol]},
                ]
            },
        }
        ws.send(json.dumps(sub))
        self._msg_count = 0
        self._price_msg_count = 0

    def _on_message(self, ws, message: str):
        try:
            msg = json.loads(message)
        except Exception:
            return
        self._msg_count = getattr(self, "_msg_count", 0) + 1
        if self._msg_count <= 3:
            preview = message[:200]
            print(f"[ws] msg#{self._msg_count}: {preview}")
        # v2/ticker payload has "mark_price" / "close" / "timestamp" (micros)
        price = None
        for k in ("close", "mark_price", "spot_price", "last_price"):
            v = msg.get(k)
            if v is not None:
                try:
                    price = float(v)
                    break
                except (TypeError, ValueError):
                    pass
        if price is None:
            return
        self._price_msg_count = getattr(self, "_price_msg_count", 0) + 1
        ts_us = msg.get("timestamp") or int(time.time() * 1_000_000)
        ts = float(ts_us) / 1_000_000 if ts_us > 10**12 else float(ts_us)
        self._emit_if_new_bucket(ts, price)

    def _on_error(self, ws, err):
        print(f"[ws] error: {err}")

    def _on_close(self, ws, *_):
        print(f"[ws] closed (running={self._running})")
        if self._running:
            time.sleep(2)
            self._connect()

    def _connect(self):
        if websocket is None:
            raise RuntimeError("websocket-client not installed; run `pip install -r requirements.txt`")
        self._ws = websocket.WebSocketApp(
            self.ws_url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._ws.run_forever(ping_interval=20, ping_timeout=10)

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._connect, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    def bars(self):
        while self._running:
            bar = self._q.get()
            yield bar
