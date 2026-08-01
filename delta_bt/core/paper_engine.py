"""Paper trading engine: consume live bars, feed strategy, either simulate
fills locally OR route orders to the demo venue."""
from __future__ import annotations

import time
from typing import Optional

from ..core.strategy import Strategy, StrategyContext
from ..core.types import RunConfig
from ..data.delta_client import DeltaClient
from ..data.live_stream import LiveBarStream
from ..execution.live_broker import LiveBroker
from ..execution.portfolio import Portfolio


def run_paper(
    ws_url: str,
    strat: Strategy,
    cfg: RunConfig,
    duration_s: Optional[int] = None,
    live_orders: bool = False,
    client: Optional[DeltaClient] = None,
    live_qty_contracts: int = 1,
) -> Portfolio:
    pf = Portfolio(
        cfg.capital,
        fee_bps=cfg.fee_bps, slippage_bps=cfg.slippage_bps,
        sl_pct=cfg.sl_pct, tp_pct=cfg.tp_pct, trail_pct=cfg.trail_pct,
        leverage=cfg.leverage,
    )
    broker: Optional[LiveBroker] = None
    if live_orders:
        assert client, "live_orders=True requires an authenticated DeltaClient"
        broker = LiveBroker(client, cfg.symbol, qty_contracts=live_qty_contracts)

    stream = LiveBarStream(ws_url, cfg.symbol, cfg.resolution)
    stream.start()
    strat.on_start()
    t0 = time.time()
    print(f"\n \033[1m{cfg.symbol} @ {cfg.resolution}\033[0m • Orders: {'Live' if live_orders else 'Simulated'} • Press Ctrl+C to stop")
    try:
        for bar in stream.bars():
            ctx = StrategyContext(pf.position, pf.equity(bar.close), pf.cash)
            sig = strat.on_bar(bar, ctx)
            pf.handle_signal(sig, bar, qty_pct=cfg.qty_pct)
            if broker is not None:
                try:
                    broker.handle_signal(sig, bar)
                except Exception as e:
                    print(f"[paper] live order failed: {e}")
            time_str = bar.ts.strftime('%H:%M:%S')
            sig_color = "\033[92m" if sig.value == "BUY" else ("\033[91m" if sig.value == "SELL" else "\033[90m")
            print(f" 🕒 {time_str}   💵 {bar.close:>8.2f}   🚦 {sig_color}{sig.value:4}\033[0m   💰 ${pf.equity(bar.close):>10.2f}")
            if duration_s and (time.time() - t0) >= duration_s:
                break
    except KeyboardInterrupt:
        print(f"\n \033[93mStream stopped by user.\033[0m")
    finally:
        stream.stop()
        strat.on_stop()
    return pf
