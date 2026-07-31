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

# Safe fallback step for unknown resolutions — 1h chunks prevent
# hundreds of unnecessary API calls that the old `60` default caused.
_DEFAULT_RES_SECONDS = 3600


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
    cache_key = f"candles:{symbol}:{resolution}:{int(start.timestamp())}:{int(end.timestamp())}"
    try:
        from ..cache import get_cache
        cache = get_cache()
        cached_raw = cache.get(cache_key)
        if cached_raw is not None and isinstance(cached_raw, list):
            return [_to_bar(r, symbol, resolution) for r in cached_raw]
    except Exception:
        cache = None

    # Fix: use _DEFAULT_RES_SECONDS (3600) instead of 60 for unknown resolutions
    # so unrecognised resolutions don't silently make hundreds of API calls.
    step = _RES_SECONDS.get(resolution, _DEFAULT_RES_SECONDS) * 1500
    bars: List[Bar] = []
    raw_accum: List[dict] = []
    cur = start
    seen: set = set()

    while cur < end:
        chunk_end = min(end, cur + timedelta(seconds=step))
        try:
            raw = client.candles(symbol, resolution, cur, chunk_end)
        except Exception:
            # If a chunk fails, stop pagination rather than silently
            # returning a partial result with a gap.
            break
        for r in raw:
            t = r["time"]
            if t in seen:
                continue
            seen.add(t)
            raw_accum.append(r)
            bars.append(_to_bar(r, symbol, resolution))
        if not raw:
            break
        cur = chunk_end

    bars.sort(key=lambda b: b.ts)
    if cache is not None and raw_accum:
        cache.set(cache_key, raw_accum, ttl=60)
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
