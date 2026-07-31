"""Bot & Position Monitor module for terminal live tracking.

Provides real-time terminal tracking for:
- Live/Paper bot status, ticks, and signals
- Open Delta Exchange positions and unrealized PnL
- Emergency position kill-switch (close-all)
"""
from __future__ import annotations

import os
import sys
import time
from typing import Dict, List, Optional
from .data.delta_client import DeltaClient
from .deployments import list_deployments
from .pnl_analytics import render_box_table, format_pnl

C_RESET   = "\033[0m"
C_BOLD    = "\033[1m"
C_GREEN   = "\033[1;32m"
C_CYAN    = "\033[1;36m"
C_YELLOW  = "\033[1;33m"
C_RED     = "\033[1;31m"
C_DIM     = "\033[2m"


def _get_venue_client(venue: str = "testnet") -> Optional[DeltaClient]:
    live = venue == "live"
    base = "https://api.india.delta.exchange" if live else os.getenv("DELTA_BASE_URL", "https://cdn-ind.testnet.deltaex.org")
    prefix = "DELTA_LIVE" if live else "DELTA_TESTNET"
    key = os.getenv(f"{prefix}_API_KEY") or os.getenv("DELTA_API_KEY", "")
    sec = os.getenv(f"{prefix}_API_SECRET") or os.getenv("DELTA_API_SECRET", "")
    if not key or not sec:
        return None
    return DeltaClient(base, key, sec)


def fetch_open_positions() -> List[Dict]:
    """Fetch all open positions from Delta Exchange across testnet & live."""
    open_positions = []
    for venue in ("testnet", "live"):
        client = _get_venue_client(venue)
        if not client:
            continue
        try:
            positions = client.positions()
            for pos in positions:
                size = float(pos.get("size", 0))
                if size != 0:
                    open_positions.append({
                        "venue": venue,
                        "symbol": pos.get("product_symbol") or pos.get("symbol"),
                        "side": "BUY" if size > 0 else "SELL",
                        "size": abs(size),
                        "entry_price": float(pos.get("entry_price") or 0),
                        "mark_price": float(pos.get("mark_price") or 0),
                        "liquidation_price": float(pos.get("liquidation_price") or 0),
                        "unrealized_pnl": float(pos.get("unrealized_pnl") or 0),
                        "leverage": pos.get("leverage", 1)
                    })
        except Exception:
            pass
    return open_positions


def emergency_close_all() -> Dict:
    """Close all open positions on Delta Exchange using market reduce-only orders."""
    results = {"closed": [], "errors": []}
    for venue in ("testnet", "live"):
        client = _get_venue_client(venue)
        if not client:
            continue
        try:
            positions = client.positions()
            for pos in positions:
                size = float(pos.get("size", 0))
                if size != 0:
                    symbol = pos.get("product_symbol") or pos.get("symbol")
                    close_side = "sell" if size > 0 else "buy"
                    qty = abs(size)
                    try:
                        res = client.place_order(
                            product_symbol=symbol,
                            size=qty,
                            side=close_side,
                            order_type="market_order",
                            reduce_only=True
                        )
                        results["closed"].append({"venue": venue, "symbol": symbol, "qty": qty, "order": res})
                    except Exception as e:
                        results["errors"].append({"venue": venue, "symbol": symbol, "error": str(e)})
        except Exception as e:
            results["errors"].append({"venue": venue, "error": str(e)})
    return results


def run_live_terminal_monitor(refresh_sec: int = 3):
    """Run an auto-refreshing live terminal dashboard."""
    print("\033[2J\033[H", end="")
    try:
        while True:
            print("\033[H", end="")
            now_str = time.strftime("%Y-%m-%d %H:%M:%S")
            print(f"{C_CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{C_RESET}")
            print(f" {C_BOLD}{C_GREEN}⚡ DELTA TERMINAL MONITOR{C_RESET} {C_DIM}[{now_str}]{C_RESET}")
            print(f"{C_CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{C_RESET}\n")

            # 1. Active Bots Table
            bots = list_deployments()
            bot_headers = ["ID", "Status", "Name", "Venue", "Strategy", "Symbol", "TF", "Ticks", "PnL ($)", "Last Signal"]
            bot_rows = []
            for b in bots:
                stat_icon = "🟢" if b["status"] == "running" else "⏸️"
                pnl_str = format_pnl(b["realized_pnl"] or 0)
                bot_rows.append([
                    str(b["id"]),
                    stat_icon,
                    str(b["name"])[:18],
                    str(b["venue"]),
                    str(b["strategy"])[:16],
                    str(b["symbol"]),
                    str(b["resolution"]),
                    str(int(b["ticks"] or 0)),
                    pnl_str,
                    str(b["last_signal"] or "-")
                ])
            print(render_box_table(bot_headers, bot_rows, title=f"ACTIVE BOTS ({len(bots)})"))

            # 2. Live Open Positions Table
            positions = fetch_open_positions()
            pos_headers = ["Venue", "Symbol", "Side", "Size", "Entry", "Mark", "Liq Price", "uPnL ($)"]
            pos_rows = []
            for p in positions:
                upnl_str = format_pnl(p["unrealized_pnl"])
                pos_rows.append([
                    p["venue"],
                    p["symbol"],
                    p["side"],
                    f"{p['size']:.4f}",
                    f"${p['entry_price']:.2f}",
                    f"${p['mark_price']:.2f}",
                    f"${p['liquidation_price']:.2f}",
                    upnl_str
                ])
            print("\n" + render_box_table(pos_headers, pos_rows, title=f"OPEN EXCHANGE POSITIONS ({len(positions)})"))

            print(f"\n{C_DIM}Auto-refresh: {refresh_sec}s | Press Ctrl+C to exit{C_RESET}")
            time.sleep(refresh_sec)
    except KeyboardInterrupt:
        print(f"\n{C_YELLOW}Monitor stopped.{C_RESET}\n")
