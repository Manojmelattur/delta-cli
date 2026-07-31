"""Unified Cache Manager for delta_bt.

Provides Redis caching with automatic graceful fallback to an in-memory TTL cache
when Redis is unavailable or unconfigured.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Try importing redis
try:
    import redis
    _HAS_REDIS_LIB = True
except ImportError:
    _HAS_REDIS_LIB = False


class InMemoryTTLCache:
    """Thread-safe in-memory key-value cache with TTL expiration."""

    def __init__(self, default_ttl: int = 60):
        self._store: Dict[str, tuple[Any, float]] = {}
        self.default_ttl = default_ttl

    def get(self, key: str) -> Optional[Any]:
        if key not in self._store:
            return None
        val, expiry = self._store[key]
        if time.time() > expiry:
            del self._store[key]
            return None
        return val

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        duration = ttl if ttl is not None else self.default_ttl
        expiry = time.time() + duration
        self._store[key] = (value, expiry)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def delete_prefix(self, prefix: str) -> None:
        keys_to_del = [k for k in self._store if k.startswith(prefix)]
        for k in keys_to_del:
            self._store.pop(k, None)

    def clear(self) -> None:
        self._store.clear()


class CacheManager:
    """Unified cache interface routing to Redis if available, else In-Memory."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        db: int = 0,
        password: Optional[str] = None,
        default_ttl: int = 60,
    ):
        self.host = host or os.getenv("REDIS_HOST", "localhost")
        try:
            self.port = int(port or os.getenv("REDIS_PORT", 6379))
        except (ValueError, TypeError):
            self.port = 6379
        self.db = db
        self.password = password or os.getenv("REDIS_PASSWORD") or None
        self.default_ttl = default_ttl

        self._redis_client: Optional[Any] = None
        self._memory_cache = InMemoryTTLCache(default_ttl=default_ttl)
        self._redis_healthy = False
        self._last_check_time = 0.0

        self._connect_redis()

    def _connect_redis(self) -> bool:
        now = time.time()
        if now - self._last_check_time < 5.0 and not self._redis_healthy:
            return False

        self._last_check_time = now
        if not _HAS_REDIS_LIB:
            self._redis_healthy = False
            return False

        try:
            redis_url = os.getenv("REDIS_URL")
            if redis_url:
                client = redis.Redis.from_url(
                    redis_url,
                    socket_connect_timeout=1.0,
                    socket_timeout=1.0,
                    decode_responses=True,
                )
            else:
                client = redis.Redis(
                    host=self.host,
                    port=self.port,
                    db=self.db,
                    password=self.password,
                    socket_connect_timeout=1.0,
                    socket_timeout=1.0,
                    decode_responses=True,
                )
            if client.ping():
                self._redis_client = client
                self._redis_healthy = True
                return True
        except Exception as e:
            logger.debug(f"Redis connection check failed: {e}")
            self._redis_client = None
            self._redis_healthy = False

        return False

    def is_redis_active(self) -> bool:
        if self._redis_healthy:
            try:
                if self._redis_client and self._redis_client.ping():
                    return True
            except Exception:
                self._redis_healthy = False
        return self._connect_redis()

    def status(self) -> Dict[str, Any]:
        redis_up = self.is_redis_active()
        return {
            "up": redis_up,
            "backend": "redis" if redis_up else "memory",
            "message": "PONG" if redis_up else "In-Memory TTL Fallback Active",
            "host": self.host if redis_up else None,
            "port": self.port if redis_up else None,
            "db": self.db,
        }

    def get(self, key: str) -> Optional[Any]:
        if self.is_redis_active() and self._redis_client:
            try:
                raw = self._redis_client.get(key)
                if raw is not None:
                    try:
                        return json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        return raw
            except Exception as e:
                logger.warning(f"Redis get error, falling back to memory: {e}")
                self._redis_healthy = False

        return self._memory_cache.get(key)

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        expire_sec = ttl if ttl is not None else self.default_ttl
        val_str = json.dumps(value) if not isinstance(value, (str, int, float, bool)) else value

        if self.is_redis_active() and self._redis_client:
            try:
                self._redis_client.set(key, val_str, ex=expire_sec)
                return
            except Exception as e:
                logger.warning(f"Redis set error, falling back to memory: {e}")
                self._redis_healthy = False

        self._memory_cache.set(key, value, ttl=expire_sec)

    def delete(self, key: str) -> None:
        if self.is_redis_active() and self._redis_client:
            try:
                self._redis_client.delete(key)
            except Exception:
                pass
        self._memory_cache.delete(key)

    def delete_prefix(self, prefix: str) -> None:
        if self.is_redis_active() and self._redis_client:
            try:
                keys = self._redis_client.keys(f"{prefix}*")
                if keys:
                    self._redis_client.delete(*keys)
            except Exception:
                pass
        self._memory_cache.delete_prefix(prefix)


_GLOBAL_CACHE: Optional[CacheManager] = None


def get_cache() -> CacheManager:
    global _GLOBAL_CACHE
    if _GLOBAL_CACHE is None:
        _GLOBAL_CACHE = CacheManager()
    return _GLOBAL_CACHE
