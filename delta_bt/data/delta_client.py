"""Delta Exchange India REST client.

Docs: https://docs.delta.exchange
Endpoints used:
- GET  /v2/products                 (list products)
- GET  /v2/history/candles          (historical OHLC)
- POST /v2/orders                   (place order)  [auth]
- GET  /v2/positions/margined       (positions)    [auth]
- GET  /v2/wallet/balances          (balances)     [auth]

Auth: HMAC-SHA256 over `method + timestamp + path + query + body`,
sent as `api-key`, `signature`, `timestamp` headers.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
import os
import sqlite3
import json

from delta_bt import config

# Optional Redis Support
try:
    import redis
    REDIS_URL = config.get_redis_url()
    if not REDIS_URL:
        conn = None
        try:
            from pathlib import Path
            db_path = config.get_db_path()
            conn = sqlite3.connect(db_path)
            row = conn.execute("SELECT value_json FROM app_settings WHERE key='redis.url'").fetchone()
            if row:
                REDIS_URL = json.loads(row[0])
        except Exception:
            pass
        finally:
            if conn:
                conn.close()
            
    redis_client = redis.from_url(REDIS_URL) if REDIS_URL else None
except ImportError:
    redis_client = None

# Fallback In-Memory Cache
_local_cache = {}

def get_cache(key: str) -> Optional[Any]:
    if redis_client:
        try:
            val = redis_client.get(key)
            return json.loads(val) if val else None
        except Exception:
            pass
    
    if key in _local_cache:
        val, ts, ttl = _local_cache[key]
        if time.time() - ts < ttl:
            return val
    return None

def set_cache(key: str, val: Any, ttl: int = 5) -> None:
    if redis_client:
        try:
            redis_client.setex(key, ttl, json.dumps(val))
            return
        except Exception:
            pass
            
    _local_cache[key] = (val, time.time(), ttl)



RESOLUTION_MAP = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "2h": "2h", "4h": "4h", "6h": "6h", "1d": "1d", "7d": "7d",
}


class DeltaClient:
    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        api_secret: str = "",
        timeout: int = 20,
    ):
        self.base_url = base_url.strip().rstrip("/")

        key = api_key.strip()
        sec = api_secret.strip()
        if not (key and sec):
            venue = "live" if ("api.india.delta.exchange" in self.base_url or "api.delta.exchange" in self.base_url) else "testnet"
            env_key, env_sec = config.get_api_credentials(venue)
            if not key:
                key = env_key
            if not sec:
                sec = env_sec

        self.api_key = key
        self.api_secret = sec
        self.timeout = timeout
        self.s = requests.Session()
        self.s.headers.update({
            "Accept": "application/json",
            "User-Agent": "delta-bt-framework/1.0",
        })

    # ------------------------------------------------------------------
    # signing
    # ------------------------------------------------------------------
    def _sign(self, method: str, path: str, query: str, body: str) -> Dict[str, str]:
        ts = str(int(time.time()))
        payload = method + ts + path + query + body
        sig = hmac.new(
            self.api_secret.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()
        return {
            "api-key": self.api_key,
            "signature": sig,
            "timestamp": ts,
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
        auth: bool = False,
    ) -> Any:
        url = self.base_url + path
        query = ""
        if params:
            # deterministic ordering matches what requests sends
            query = "?" + "&".join(f"{k}={v}" for k, v in params.items())
        body_str = json.dumps(body, separators=(",", ":")) if body else ""

        headers = {}
        if auth:
            if not (self.api_key and self.api_secret):
                raise RuntimeError("API key/secret required for this endpoint")
            headers = self._sign(method, path, query, body_str)

        # Retry with exponential backoff on 429 (rate limit) and 5xx errors.
        # Delta India quota: 10,000 weight / 5-min window. On 429 the
        # X-RATE-LIMIT-RESET header (microseconds) says when the window resets.
        last_err: Optional[Exception] = None
        r: Optional[requests.Response] = None
        for attempt in range(4):  # 1 try + 3 retries
            r = self.s.request(
                method,
                url + (query if params else ""),
                data=body_str if body_str else None,
                headers=headers,
                timeout=self.timeout,
            )
            if r.status_code == 429:
                # rate limited — wait for reset (capped) then retry
                reset_us = r.headers.get("X-RATE-LIMIT-RESET")
                try:
                    wait_s = min(float(reset_us) / 1_000_000.0, 30.0) if reset_us else 5.0 * (attempt + 1)
                except (TypeError, ValueError):
                    wait_s = 5.0 * (attempt + 1)
                last_err = RuntimeError(f"Delta API 429 rate limited (attempt {attempt + 1})")
                if attempt < 3:
                    time.sleep(max(wait_s, 1.0))
                    if auth:  # timestamp must be fresh after sleeping
                        headers = self._sign(method, path, query, body_str)
                    continue
                raise last_err
            if r.status_code >= 500:
                last_err = RuntimeError(f"Delta API {r.status_code} server error (attempt {attempt + 1})")
                if attempt < 3:
                    time.sleep(2.0 * (attempt + 1))
                    if auth:
                        headers = self._sign(method, path, query, body_str)
                    continue
                raise last_err
            break

        assert r is not None  # loop always executes at least once

        try:
            data = r.json()
        except Exception:
            r.raise_for_status()
            raise
        if not r.ok or (isinstance(data, dict) and data.get("success") is False):
            raise RuntimeError(f"Delta API error {r.status_code}: {data}")
        return data.get("result", data) if isinstance(data, dict) else data

    # ------------------------------------------------------------------
    # public
    # ------------------------------------------------------------------
    def products(self) -> List[Dict[str, Any]]:
        cache_key = "delta:products"
        cached = get_cache(cache_key)
        if cached:
            return cached
            
        data = self._request("GET", "/v2/products")
        set_cache(cache_key, data, ttl=600)  # products list rarely changes — 10 min
        return data

    def get_product(self, symbol: str) -> Dict[str, Any]:
        for p in self.products():
            if p.get("symbol") == symbol:
                return p
        raise ValueError(f"Symbol {symbol} not found on {self.base_url}")

    def tickers(self, contract_types: Optional[str] = None) -> List[Dict[str, Any]]:
        """Live per-symbol snapshot: mark_price, volume, turnover_usd,
        open_interest, funding_rate, high/low/close, ...

        `contract_types` is a comma-separated filter (e.g. "perpetual_futures").
        """
        cache_key = f"delta:tickers:{contract_types}"
        cached = get_cache(cache_key)
        if cached:
            return cached

        params = {"contract_types": contract_types} if contract_types else None
        data = self._request("GET", "/v2/tickers", params=params)
        set_cache(cache_key, data, ttl=30)  # tickers: 30s is fresh enough for scanners
        return data

    def ticker(self, symbol: str) -> Dict[str, Any]:
        """Current per-symbol ticker snapshot, including mark_price."""
        cache_key = f"delta:ticker:{symbol}"
        cached = get_cache(cache_key)
        if cached:
            return cached
            
        data = self._request("GET", f"/v2/tickers/{symbol}")
        set_cache(cache_key, data)
        return data

    def rate_limit_quota(self) -> Dict[str, Any]:
        """Remaining API quota: {'current_quota': N, 'remaining_time_in_milliseconds': M}.
        Delta India allows 10,000 weight units per 5-minute window."""
        return self._request("GET", "/v2/rate_limits/quota", auth=True)


    def candles(
        self,
        symbol: str,
        resolution: str,
        start: datetime,
        end: datetime,
    ) -> List[Dict[str, Any]]:
        """Historical OHLC. Returns list of dicts sorted ascending by time."""
        res = RESOLUTION_MAP.get(resolution, resolution)
        start_ts = int(start.replace(tzinfo=timezone.utc).timestamp())
        end_ts = int(end.replace(tzinfo=timezone.utc).timestamp())
        
        cache_key = f"delta:candles:{symbol}:{res}:{start_ts}:{end_ts}"
        cached = get_cache(cache_key)
        if cached:
            return cached

        params = {
            "symbol": symbol,
            "resolution": res,
            "start": start_ts,
            "end": end_ts,
        }
        data = self._request("GET", "/v2/history/candles", params=params)
        # data is list of {time, open, high, low, close, volume}
        data = sorted(data, key=lambda x: x["time"])
        set_cache(cache_key, data)
        return data

    # ------------------------------------------------------------------
    # authenticated
    # ------------------------------------------------------------------
    def balances(self) -> List[Dict[str, Any]]:
        return self._request("GET", "/v2/wallet/balances", auth=True)

    def positions(self) -> List[Dict[str, Any]]:
        """Open margined positions on this venue."""
        return self._request("GET", "/v2/positions/margined", auth=True)

    def place_order(
        self,
        product_id: int,
        size: int,
        side: str,               # "buy" | "sell"
        order_type: str = "market_order",
        limit_price: Optional[str] = None,
        reduce_only: bool = False,
        time_in_force: str = "gtc",
        post_only: bool = False,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "product_id": product_id,
            "size": size,
            "side": side,
            "order_type": order_type,
            "reduce_only": reduce_only,
            "time_in_force": time_in_force,
            "post_only": post_only,
        }
        if limit_price is not None:
            body["limit_price"] = limit_price
        return self._request("POST", "/v2/orders", body=body, auth=True)

    def place_stop_order(
        self,
        product_id: int,
        size: int,
        side: str,                       # opposite of position side
        stop_price: float,
        stop_order_type: str,            # "stop_loss_order" | "take_profit_order"
        trigger: str,                    # "above" | "below" — required, Delta defaults to "above" otherwise
    ) -> Dict[str, Any]:
        """Reduce-only exchange-side bracket (SL or TP) triggered by mark price."""
        body: Dict[str, Any] = {
            "product_id": product_id,
            "size": size,
            "side": side,
            "order_type": "market_order",
            "reduce_only": True,
            "stop_order_type": stop_order_type,
            "stop_price": str(stop_price),
            "trigger": trigger,
            "stop_trigger_method": "mark_price",
            "time_in_force": "gtc",
        }
        return self._request("POST", "/v2/orders", body=body, auth=True)

    def cancel_order(self, product_id: int, order_id: int) -> Dict[str, Any]:
        return self._request("DELETE", "/v2/orders",
                             body={"id": order_id, "product_id": product_id}, auth=True)

    def set_leverage(self, product_id: int, leverage: float) -> Dict[str, Any]:
        """POST /v2/products/{product_id}/orders/leverage — set account leverage
        for this perp. Delta rejects the call while a position is open on the
        product; callers should catch and treat that as a soft warning."""
        return self._request(
            "POST",
            f"/v2/products/{product_id}/orders/leverage",
            body={"leverage": str(leverage)},
            auth=True,
        )
