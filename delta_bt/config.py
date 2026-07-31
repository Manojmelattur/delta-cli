"""Centralized Configuration Module for delta_bt.

Loads environment variables from .env file and provides helper functions
to access configuration for API keys, URLs, Database paths, Redis, and Telegram.
"""

from pathlib import Path
import os
from typing import Tuple, Optional
# Path resolution: find .env in project root
ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT_DIR / ".env"

# Safe dotenv loader with native fallback if python-dotenv is not installed
try:
    from dotenv import load_dotenv
    if ENV_PATH.exists():
        load_dotenv(dotenv_path=ENV_PATH)
    else:
        load_dotenv()
except ImportError:
    if ENV_PATH.exists():
        try:
            with open(ENV_PATH, "r", encoding="utf-8") as _f:
                for _line in _f:
                    _line = _line.strip()
                    if _line and not _line.startswith("#") and "=" in _line:
                        _k, _v = _line.split("=", 1)
                        _k = _k.strip()
                        _v = _v.strip().strip("'\"")
                        if _k and _k not in os.environ:
                            os.environ[_k] = _v
        except Exception:
            pass


def get_api_credentials(venue: str = "testnet") -> Tuple[str, str]:
    """Retrieve API key and secret for the specified venue ('live' or 'testnet')."""
    v = venue.lower().strip()
    if v in ("live", "production", "prod"):
        key = os.getenv("DELTA_LIVE_API_KEY") or os.getenv("DELTA_API_KEY", "")
        sec = os.getenv("DELTA_LIVE_API_SECRET") or os.getenv("DELTA_API_SECRET", "")
    else:
        key = os.getenv("DELTA_TESTNET_API_KEY") or os.getenv("DELTA_API_KEY", "")
        sec = os.getenv("DELTA_TESTNET_API_SECRET") or os.getenv("DELTA_API_SECRET", "")
    return key.strip(), sec.strip()


def get_base_url(venue: str = "testnet") -> str:
    """Retrieve REST API base URL for the specified venue."""
    v = venue.lower().strip()
    if v in ("live", "production", "prod"):
        return os.getenv("DELTA_LIVE_BASE_URL", "https://api.india.delta.exchange").strip()
    return os.getenv("DELTA_TESTNET_BASE_URL") or os.getenv("DELTA_BASE_URL", "https://cdn-ind.testnet.deltaex.org").strip()


def get_ws_url(venue: str = "testnet") -> str:
    """Retrieve WebSocket URL for the specified venue."""
    v = venue.lower().strip()
    if v in ("live", "production", "prod"):
        return os.getenv("DELTA_LIVE_WS_URL", "wss://socket.india.delta.exchange").strip()
    return os.getenv("DELTA_TESTNET_WS_URL") or os.getenv("DELTA_WS_URL", "wss://socket-ind.testnet.deltaex.org").strip()


def get_db_path() -> str:
    """Retrieve default SQLite database path."""
    db_path = os.getenv("DELTA_BT_DB")
    if db_path:
        return db_path
    return str(ROOT_DIR / "data" / "delta_bt.sqlite")


def get_redis_url() -> Optional[str]:
    """Retrieve Redis connection URL."""
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        return redis_url
    host = os.getenv("REDIS_HOST", "localhost")
    port = os.getenv("REDIS_PORT", "6379")
    password = os.getenv("REDIS_PASSWORD")
    if password:
        return f"redis://:{password}@{host}:{port}/0"
    return f"redis://{host}:{port}/0"


def get_telegram_config() -> Tuple[Optional[str], Optional[str]]:
    """Retrieve Telegram Bot Token and Chat ID."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    return token, chat_id


def get_max_sl_slippage_pct() -> float:
    """Retrieve maximum stop-loss slippage percentage."""
    try:
        return float(os.getenv("MAX_SL_SLIPPAGE_PCT", "1.0"))
    except ValueError:
        return 1.0
