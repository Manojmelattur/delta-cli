"""Historical bar loader — pulls from Delta REST and paginates as needed."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterator, List

from ..core.types import Bar
from .delta_client import DeltaClient


# Approximate max bars per request; Delta caps around 2000. We chunk by time.
_RES_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600,
    "1d": 86400, "7d": 604800,
}


def _to_bar(raw: dict, symbol: str, resolution: str) -> Bar:
    return Bar(
        ts=datetime.fromtimestamp(raw["time"], tz=timezone.utc),
        open=float(raw["open"]),
        high=float(raw["high"]),
        low=float(raw["low"]),
        close=float(raw["close"]),
        volume=float(raw.get("volume", 0)),
        symbol=symbol,
        resolution=resolution,
    )


def load_history(
    client: DeltaClient,
    symbol: str,
    resolution: str,
    start: datetime,
    end: datetime,
) -> List[Bar]:
    step = _RES_SECONDS.get(resolution, 60) * 1500
    bars: List[Bar] = []
    cur = start
    seen = set()
    while cur < end:
        chunk_end = min(end, cur + timedelta(seconds=step))
        raw = client.candles(symbol, resolution, cur, chunk_end)
        for r in raw:
            t = r["time"]
            if t in seen:
                continue
            seen.add(t)
            bars.append(_to_bar(r, symbol, resolution))
        if not raw:
            break
        cur = chunk_end
    bars.sort(key=lambda b: b.ts)
    return bars


def iter_history(
    client: DeltaClient,
    symbol: str,
    resolution: str,
    start: datetime,
    end: datetime,
) -> Iterator[Bar]:
    for b in load_history(client, symbol, resolution, start, end):
        yield b
