"""Command-line entry point.

Subcommands:
    backtest         run against historical candles
    paper            paper trade on live data (demo/testnet, or sim only)
    live             REAL orders on the production venue (requires --i-understand)
    list-strategies  print available strategies
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass

from .core.engine import run_backtest
from .core.paper_engine import run_paper
from .core.registry import discover_strategies, load_strategy
from .core.types import RunConfig
from .data.delta_client import DeltaClient
from .data.history import load_history
from .reports.report import write_report

DEFAULT_BASE_DEMO = os.getenv("DELTA_BASE_URL", "https://cdn-ind.testnet.deltaex.org")
DEFAULT_WS_DEMO = os.getenv("DELTA_WS_URL", "wss://socket-ind.testnet.deltaex.org")
DEFAULT_BASE_LIVE = "https://api.india.delta.exchange"
DEFAULT_WS_LIVE = "wss://socket.india.delta.exchange"


def _parse_dt(s: str) -> datetime:
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    raise argparse.ArgumentTypeError(f"Bad datetime: {s}")


def _parse_params(s: str) -> dict:
    if not s:
        return {}
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        raise argparse.ArgumentTypeError(f"--params must be JSON: {e}")


def _add_common(sp):
    sp.add_argument("--strategy", required=True)
    sp.add_argument("--symbol", required=True, help="e.g. BTCUSD, ETHUSD")
    sp.add_argument(
        "--timeframe",
        "--resolution",
        dest="resolution",
        default="5m",
        help="1m,3m,5m,15m,30m,1h,2h,4h,6h,1d,7d",
    )
    sp.add_argument("--capital", type=float, default=10_000.0)
    sp.add_argument(
        "--params",
        type=_parse_params,
        default={},
        help='JSON string, e.g. \'{"fast":9,"slow":21}\'',
    )
    sp.add_argument("--fee-bps", type=float, default=5.0)
    sp.add_argument("--slippage-bps", type=float, default=2.0)
    sp.add_argument(
        "--qty-pct", type=float, default=1.0, help="Fraction of equity per trade (0-1)"
    )
    sp.add_argument(
        "--leverage",
        type=float,
        default=1.0,
        help="Futures leverage multiplier applied to sizing",
    )
    # risk management
    sp.add_argument(
        "--sl-pct", type=float, default=0.0, help="Stop loss %% of entry (0 = disabled)"
    )
    sp.add_argument(
        "--tp-pct",
        type=float,
        default=0.0,
        help="Take profit %% of entry (0 = disabled)",
    )
    sp.add_argument(
        "--trail-pct",
        "--trailing-sl",
        dest="trail_pct",
        type=float,
        default=0.0,
        help="Trailing stop %% from peak/trough (0 = disabled)",
    )
    # regime filter
    sp.add_argument(
        "--adx-filter",
        action="store_true",
        help="Only take entries whose strategy regime (trend/range) "
        "matches current ADX. Cuts whipsaws in the wrong regime.",
    )
    sp.add_argument("--adx-len", type=int, default=14)
    sp.add_argument(
        "--adx-trend-min",
        type=float,
        default=20.0,
        help="ADX >= this counts as 'trend' regime (default 20)",
    )
    sp.add_argument(
        "--adx-range-max",
        type=float,
        default=20.0,
        help="ADX <  this counts as 'range' regime (default 20)",
    )
    sp.add_argument(
        "--adx-exit-on-flip",
        action="store_true",
        help="Close an open position when ADX regime no longer matches "
        "the strategy's regime tag",
    )
    sp.add_argument(
        "--adx-tighten-trail-on-flip",
        type=float,
        default=0.0,
        help="If >0, temporarily override --trail-pct to this tighter "
        "value while regime is mismatched (e.g. 0.4)",
    )
    sp.add_argument(
        "--diagnostics",
        action="store_true",
        help="Record per-bar ADX / regime / stop-level rows to "
        "diagnostics.csv (renderable with `plot-diag`)",
    )
    # env
    sp.add_argument("--base-url", default=None)
    sp.add_argument("--ws-url", default=None)
    sp.add_argument(
        "--api-key",
        default=None,
        help="Overrides env. If omitted, reads DELTA_LIVE_API_KEY "
        "when --live is set, else DELTA_TESTNET_API_KEY, "
        "falling back to DELTA_API_KEY.",
    )
    sp.add_argument(
        "--api-secret",
        default=None,
        help="See --api-key; corresponding *_SECRET env vars.",
    )
    sp.add_argument("--reports-dir", default="./reports")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="delta_bt",
        description="Delta Exchange India — backtest / paper / live trading framework",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("backtest", help="Run backtest on historical candles")
    _add_common(b)
    g = b.add_mutually_exclusive_group()
    g.add_argument(
        "--days",
        type=int,
        default=None,
        help="Backtest window = last N days (alternative to --start/--end)",
    )
    b.add_argument("--start", type=_parse_dt, default=None)
    b.add_argument("--end", type=_parse_dt, default=None)
    venue = b.add_mutually_exclusive_group()
    venue.add_argument(
        "--live",
        dest="live",
        action="store_true",
        default=None,
        help="Pull history from production venue (default; read-only, no orders).",
    )
    venue.add_argument(
        "--testnet",
        dest="live",
        action="store_false",
        help="Force testnet endpoint (limited history).",
    )

    pp = sub.add_parser("paper", help="Paper trade on live data (demo/testnet)")
    _add_common(pp)
    pp.add_argument(
        "--duration",
        type=int,
        default=None,
        help="Seconds to run; omit to run until Ctrl-C",
    )
    pp_venue = pp.add_mutually_exclusive_group()
    pp_venue.add_argument(
        "--live",
        dest="live",
        action="store_true",
        default=None,
        help="Stream market data from the production venue (recommended; "
             "testnet ticks are often too sparse to build bars).",
    )
    pp_venue.add_argument(
        "--testnet",
        dest="live",
        action="store_false",
        help="Stream from testnet (default).",
    )
    pp.add_argument(
        "--live-orders",
        action="store_true",
        help="POST real orders to the demo venue (still testnet)",
    )
    pp.add_argument(
        "--live-qty", type=int, default=1, help="Contracts per order when --live-orders"
    )
    pp.add_argument("--single-run", action="store_true", help="Evaluate once and place an order (redirects to trade)")

    lv = sub.add_parser("live", help="REAL orders on the production venue")
    _add_common(lv)
    lv.add_argument("--duration", type=int, default=None)
    lv.add_argument("--live-qty", type=int, default=1, help="Contracts per order")
    lv.add_argument(
        "--i-understand",
        action="store_true",
        help="Required. Confirms you will trade real funds.",
    )
    lv.add_argument("--single-run", action="store_true", help="Evaluate once and place an order (redirects to trade)")

    sub.add_parser("list-strategies", help="List available strategies")

    lr = sub.add_parser("runs", help="List past runs stored in SQLite")
    lr.add_argument("--limit", type=int, default=25)
    lr.add_argument("--strategy", default=None)
    lr.add_argument("--symbol", default=None)

    cs = sub.add_parser("compare", help="Compare strategies across stored runs")
    cs.add_argument("--symbol", default=None)

    pl = sub.add_parser("plot", help="Render equity-curve PNG(s) from SQLite")
    pl.add_argument(
        "--run-id",
        action="append",
        default=[],
        help="Run ID to plot (repeatable). Omit to auto-select recent runs.",
    )
    pl.add_argument("--strategy", default=None, help="Filter when auto-selecting")
    pl.add_argument("--symbol", default=None, help="Filter when auto-selecting")
    pl.add_argument(
        "--last",
        type=int,
        default=5,
        help="How many recent runs to plot when --run-id is omitted",
    )
    pl.add_argument(
        "--out", default="./reports/plots/equity.png", help="Output PNG path"
    )
    pl.add_argument(
        "--normalize",
        action="store_true",
        help="Normalize each curve to 100 at start (for fair comparison)",
    )
    pl.add_argument("--title", default=None)
    pl.add_argument(
        "--markers",
        action="store_true",
        help="Overlay entry (▲ long / ▼ short) and exit (● win / ✕ loss) markers",
    )

    pd_ = sub.add_parser(
        "plot-diag",
        help="Render an ADX / regime / stop-level chart for one run "
        "(needs a run produced with --diagnostics)",
    )
    pd_.add_argument(
        "--run-dir",
        default=None,
        help="Path to the run's report dir (e.g. ./reports/backtest_20260704_120000)",
    )
    pd_.add_argument(
        "--run-id",
        default=None,
        help="Run ID (used with --reports-dir if --run-dir omitted)",
    )
    pd_.add_argument("--reports-dir", default="./reports")
    pd_.add_argument(
        "--out", default=None, help="Output PNG (default: <run-dir>/adx_regime.png)"
    )
    pd_.add_argument("--title", default=None)
    pd_.add_argument(
        "--csv-only",
        action="store_true",
        help="Skip rendering the PNG, just print the diagnostics CSV path",
    )

    sv = sub.add_parser("serve", help="Run local web UI backend (FastAPI on :8000)")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--db", default=None, help="Override sqlite DB path")

    sc = sub.add_parser(
        "scan", help="Backtest ALL strategies on one symbol/timeframe and rank them"
    )
    sc.add_argument("--symbol", required=True, help="e.g. BTCUSD, ETHUSD")
    sc.add_argument("--timeframe", "--resolution", dest="resolution", default="15m")
    sc.add_argument("--days", type=int, default=30)
    sc.add_argument("--start", type=_parse_dt, default=None)
    sc.add_argument("--end", type=_parse_dt, default=None)
    sc.add_argument("--capital", type=float, default=10_000.0)
    sc.add_argument("--fee-bps", type=float, default=5.0)
    sc.add_argument("--slippage-bps", type=float, default=2.0)
    sc.add_argument("--qty-pct", type=float, default=1.0)
    sc.add_argument("--leverage", type=float, default=1.0)
    sc.add_argument("--sl-pct", type=float, default=1.2)
    sc.add_argument("--tp-pct", type=float, default=2.4)
    sc.add_argument(
        "--trail-pct", "--trailing-sl", dest="trail_pct", type=float, default=0.8
    )
    sc.add_argument(
        "--top", type=int, default=0, help="Show only top N by return (0 = all)"
    )
    sc.add_argument(
        "--min-trades",
        type=int,
        default=1,
        help="Ignore strategies with fewer trades than this",
    )
    sc.add_argument(
        "--profitable-only",
        action="store_true",
        help="Only print strategies with return_pct > 0",
    )
    sc.add_argument(
        "--save",
        action="store_true",
        help="Persist each strategy's run to SQLite (default: off)",
    )
    sc.add_argument("--reports-dir", default="./reports")
    sc.add_argument("--base-url", default=None)
    sc.add_argument("--api-key", default=None)
    sc.add_argument("--api-secret", default=None)
    scv = sc.add_mutually_exclusive_group()
    scv.add_argument(
        "--live",
        dest="live",
        action="store_true",
        default=None,
        help="Pull history from production venue (default).",
    )
    scv.add_argument(
        "--testnet",
        dest="live",
        action="store_false",
        help="Force testnet endpoint (limited history).",
    )
    sc.add_argument(
        "--adx-filter",
        action="store_true",
        help="Apply ADX regime filter to every strategy in the scan",
    )
    sc.add_argument("--adx-len", type=int, default=14)
    sc.add_argument("--adx-trend-min", type=float, default=20.0)
    sc.add_argument("--adx-range-max", type=float, default=20.0)
    sc.add_argument("--adx-exit-on-flip", action="store_true")
    sc.add_argument("--adx-tighten-trail-on-flip", type=float, default=0.0)

    ru = sub.add_parser(
        "rank-universe",
        help="Rank tradable perps by liquidity + ADX regime + volatility "
        "and write a scorecard CSV",
    )
    ru.add_argument(
        "--timeframe",
        "--resolution",
        dest="resolution",
        default="1h",
        help="Bar size used to compute ADX / ATR%%",
    )
    ru.add_argument(
        "--lookback-bars",
        type=int,
        default=168,
        help="How many bars back for ret/RS (default 168 = 1w on 1h)",
    )
    ru.add_argument("--adx-len", type=int, default=14)
    ru.add_argument("--adx-trend-min", type=float, default=25.0)
    ru.add_argument("--adx-range-max", type=float, default=20.0)
    ru.add_argument(
        "--min-turnover-usd",
        type=float,
        default=20_000_000.0,
        help="Reject symbols with 24h turnover below this",
    )
    ru.add_argument(
        "--max-funding-pct",
        type=float,
        default=0.05,
        help="Reject symbols with |funding_rate| above this %%",
    )
    ru.add_argument("--atr-min-pct", type=float, default=0.5)
    ru.add_argument("--atr-max-pct", type=float, default=8.0)
    ru.add_argument(
        "--quote-suffix",
        default="USD",
        help="Only rank symbols ending in this quote (e.g. USD)",
    )
    ru.add_argument("--contract-types", default="perpetual_futures")
    ru.add_argument(
        "--regime-bias",
        choices=["any", "trend", "range"],
        default="any",
        help="Weight the composite score toward trend or range setups",
    )
    ru.add_argument("--top", type=int, default=20)
    ru.add_argument("--workers", type=int, default=8)
    ru.add_argument(
        "--out",
        default="./reports/universe/universe.csv",
        help="Where to write the scorecard CSV",
    )
    ru.add_argument("--base-url", default=None)
    ru.add_argument("--api-key", default=None)
    ru.add_argument("--api-secret", default=None)
    ru.add_argument(
        "--live",
        action="store_true",
        help="Use production venue (default: demo/testnet)",
    )

    bal = sub.add_parser("balance", help="Check Delta wallet balances")
    bal.add_argument("--base-url", default=None)
    bal.add_argument("--api-key", default=None)
    bal.add_argument("--api-secret", default=None)
    bal_group = bal.add_mutually_exclusive_group()
    bal_group.add_argument(
        "--live",
        dest="live",
        action="store_true",
        default=None,
        help="Use production venue",
    )
    bal_group.add_argument(
        "--testnet",
        dest="live",
        action="store_false",
        help="Use testnet/demo venue",
    )
    tr = sub.add_parser(
        "trade",
        help="One-shot: evaluate a strategy on recent candles and place a market order if it fires",
    )
    _add_common(tr)
    tr.add_argument("--venue", choices=["paper", "paper_live", "testnet", "live"], default="testnet")
    tr.add_argument("--size", type=int, default=1, help="Contracts per order")
    tr.add_argument("--warmup-bars", type=int, default=400)
    tr.add_argument("--dry-run", action="store_true", help="Evaluate only; do not place an order")
    tr.add_argument("--reduce-only", action="store_true")
    tr.add_argument("--i-understand-live", action="store_true", help="Required for --venue live")
    tr.add_argument("--single-run", action="store_true", help="Alias (trade is inherently a single-run)")

    od = sub.add_parser("order", help="Place an immediate market/limit order without strategy evaluation")
    od.add_argument("--venue", choices=["paper", "paper_live", "testnet", "live"], default="testnet")
    od.add_argument("--symbol", required=True)
    od.add_argument("--side", choices=["buy", "sell"], required=True)
    od.add_argument("--size", type=int, required=True)
    od.add_argument("--type", "--order-type", dest="order_type", choices=["market_order", "limit_order", "market", "limit"], default="market_order")
    od.add_argument("--limit-price", default=None)
    od.add_argument("--reduce-only", action="store_true")
    od.add_argument("--base-url", default=None)
    od.add_argument("--api-key", default=None)
    od.add_argument("--api-secret", default=None)
    od.add_argument("--i-understand-live", action="store_true", help="Required for --venue live")

    w = sub.add_parser("watch", help="Run the deployment scheduler loop (Ctrl-C to stop)")
    w.add_argument("--interval", type=int, default=15, help="Loop tick seconds (default 15)")
    w.add_argument("--once", "--single-run", dest="once", action="store_true", help="Run one tick and exit")

    dp = sub.add_parser("deployments", help="Manage scheduled strategy deployments")
    dsub = dp.add_subparsers(dest="dcmd", required=True)
    dlist = dsub.add_parser("list", help="Show all deployments with status/PnL")
    dlist.add_argument("--status", choices=["running", "paused", "stopped"], default=None, help="Filter by bot status")
    dlist.add_argument("--venue", choices=["paper", "paper_live", "testnet", "live"], default=None, help="Filter by venue")
    dlist.add_argument("--strategy", default=None, help="Filter by strategy")
    dlist.add_argument("--symbol", default=None, help="Filter by symbol")

    da = dsub.add_parser("add", help="Create a new deployment")
    da.add_argument("--name", required=True)
    da.add_argument("--venue", choices=["paper", "paper_live", "testnet", "live"], required=True)
    da.add_argument("--strategy", required=True)
    da.add_argument("--symbol", required=True)
    da.add_argument("--resolution", default="15m")
    da.add_argument("--size", type=float, required=True)
    da.add_argument("--params", type=_parse_params, default={})
    da.add_argument("--sl-pct", type=float, default=0)
    da.add_argument("--tp-pct", type=float, default=0)
    da.add_argument("--trail-pct", type=float, default=0)
    da.add_argument("--interval", type=int, default=300, help="Seconds between checks")
    da.add_argument("--reduce-only", action="store_true")
    da.add_argument("--i-understand-live", action="store_true")
    for name in ("pause", "resume", "stop", "close", "rm"):
        p2 = dsub.add_parser(name, help=f"{name} deployment")
        p2.add_argument("pos_id", type=int, nargs="?", default=None, help="Deployment ID (positional)")
        p2.add_argument("--id", type=int, dest="opt_id", default=None, help="Deployment ID")
        p2.add_argument("--venue", choices=["paper", "paper_live", "testnet", "live"], default=None, help="Filter by venue")
        p2.add_argument("--all", action="store_true", help=f"{name} all deployments")

    sa = dsub.add_parser("stop-all", help="Stop all active bot deployments")
    sa.add_argument("--venue", choices=["paper", "paper_live", "testnet", "live"], default=None, help="Filter by venue")

    pa = dsub.add_parser("pause-all", help="Pause all active bot deployments")
    pa.add_argument("--venue", choices=["paper", "paper_live", "testnet", "live"], default=None, help="Filter by venue")

    ra = dsub.add_parser("resume-all", help="Resume all bot deployments")
    ra.add_argument("--venue", choices=["paper", "paper_live", "testnet", "live"], default=None, help="Filter by venue")

    de = dsub.add_parser("edit", help="Edit bot parameters (venue, size, SL/TP, strategy, etc.)")
    de.add_argument("pos_id", type=int, nargs="?", default=None, help="Bot ID (positional)")
    de.add_argument("--id",                type=int,   dest="opt_id",  default=None)
    de.add_argument("--name",              default=None, help="New name")
    de.add_argument("--venue",             choices=["paper", "paper_live", "testnet", "live"], default=None)
    de.add_argument("--strategy",          default=None)
    de.add_argument("--symbol",            default=None)
    de.add_argument("--resolution",        default=None)
    de.add_argument("--size",              type=float, default=None, help="Lot size (contracts)")
    de.add_argument("--sl-pct",            type=float, default=None, dest="sl_pct")
    de.add_argument("--tp-pct",            type=float, default=None, dest="tp_pct")
    de.add_argument("--trail-pct",         type=float, default=None, dest="trail_pct")
    de.add_argument("--trail-activate-pct",type=float, default=None, dest="trail_activate_pct")
    de.add_argument("--breakeven-pct",     type=float, default=None, dest="breakeven_after_pct")
    de.add_argument("--leverage",          type=float, default=None)
    de.add_argument("--interval",          type=int,   default=None, help="Tick interval (sec)")
    de.add_argument("--params",            default=None, help="JSON params string (replaces existing)")
    de.add_argument("--status",            choices=["running", "paused", "stopped"], default=None)


    fo = sub.add_parser("folio", help="Portfolio snapshot: balances + open positions + bot PnL")
    fo.add_argument("--venue", choices=["testnet", "live", "both"], default="both")
    fo.add_argument("--json", action="store_true", help="Emit raw JSON instead of tables")

    tl = sub.add_parser("trades", help="List trades stored in SQLite (across runs)")
    tl.add_argument("--run", dest="run_id", default=None, help="Filter by run_id")
    tl.add_argument("--strategy", default=None)
    tl.add_argument("--symbol", default=None)
    tl.add_argument("--limit", type=int, default=50)

    rs = sub.add_parser("run-show", help="Show one stored run: summary + trades")
    rs.add_argument("run_id")
    rs.add_argument("--limit-trades", type=int, default=200)

    ac = sub.add_parser("activity", help="Show bot activity events (start/tick/order/error) for deployments")
    ac.add_argument("--id", type=int, default=None, help="Deployment id (default: all running)")
    ac.add_argument("--limit", type=int, default=50)
    ac.add_argument("--kind", default=None, help="Filter: start|tick|entry|exit|sl_hit|tp_hit|trail_hit|flip|error|stopped")

    bt = sub.add_parser("bots", help="List running bots with status/PnL/ticks")
    bt.add_argument("--all", action="store_true", help="Include stopped/paused bots too")
    bt.add_argument("--status", choices=["running", "paused", "stopped"], default=None, help="Filter by bot status")
    bt.add_argument("--venue", choices=["paper", "paper_live", "testnet", "live"], default=None, help="Filter by venue")
    bt.add_argument("--strategy", default=None, help="Filter by strategy")
    bt.add_argument("--symbol", default=None, help="Filter by symbol")

    bs = sub.add_parser("bot-show", help="Show a bot's full config + latest events")
    bs.add_argument("pos_id", type=int, nargs="?", default=None, help="Bot ID (positional)")
    bs.add_argument("--id", type=int, dest="opt_id", default=None, help="Bot ID")
    bs.add_argument("--limit", type=int, default=25)

    be = sub.add_parser("bot-events", help="Stream one bot's event history (JSON)")
    be.add_argument("pos_id", type=int, nargs="?", default=None, help="Bot ID (positional)")
    be.add_argument("--id", type=int, dest="opt_id", default=None, help="Bot ID")
    be.add_argument("--limit", type=int, default=200)
    be.add_argument("--kind", default=None)

    di = sub.add_parser("db-info", help="Show resolved SQLite path, size and row counts")
    di.add_argument("--json", action="store_true")

    sub.add_parser("db-path", help="Print the resolved SQLite path")

    dv = sub.add_parser("db-vacuum", help="VACUUM + ANALYZE the SQLite file")

    dc = sub.add_parser("db-clear", help="Delete all rows from a table (or 'all')")
    dc.add_argument("table", help="runs | trades | equity | fills | deployments | deployment_events | all")
    dc.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")

    fr = sub.add_parser("factory-reset", help="Reset database, deployments, & reports to fresh state for new users")
    fr.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")

    ad = sub.add_parser("auto-deploy", help="Auto-scan market and deploy best strategy")
    ad.add_argument("--top", type=int, default=1, help="Number of top coins to deploy on")
    ad.add_argument("--venue", choices=["paper", "paper_live", "testnet", "live"], default=None, help="Target execution venue (default: testnet)")
    ad_venue = ad.add_mutually_exclusive_group()
    ad_venue.add_argument("--live", dest="live", action="store_true", help="Use live market")
    ad_venue.add_argument("--testnet", dest="live", action="store_false", help="Use testnet")
    ad.set_defaults(live=False)
    ad.add_argument("--symbol", default=None, help="Optional specific symbol to auto-deploy (skips market scan)")
    ad.add_argument("--timeframe", "--resolution", dest="resolution", default="15m", help="Timeframe to sweep (e.g. 1m, 5m, 15m, 1h, 4h, 1d) (default: 15m)")
    ad.add_argument("--days", type=int, default=7, help="Lookback days for market scanning and strategy sweep (default: 7)")
    ad.add_argument("--size", type=float, default=0.001, help="Order size per deployment")
    ad.add_argument("--sl-pct", type=float, default=1.2, help="Stop loss percentage")
    ad.add_argument("--tp-pct", type=float, default=2.4, help="Take profit percentage")
    ad.add_argument("--trail-pct", type=float, default=0.8, help="Trailing stop percentage")

    sw = sub.add_parser(
        "sweep",
        help="Run all strategies on one symbol and print a ranked leaderboard "
             "(PnL, Sharpe, win rate, max drawdown)",
    )
    sw.add_argument("--symbol", default="BTCUSD", help="e.g. BTCUSD (default), ETHUSD")
    sw.add_argument("--timeframe", "--resolution", dest="resolution", default="15m")
    sw.add_argument("--days", type=int, default=30)
    sw.add_argument("--start", type=_parse_dt, default=None)
    sw.add_argument("--end", type=_parse_dt, default=None)
    sw.add_argument("--capital", type=float, default=10_000.0)
    sw.add_argument("--fee-bps", type=float, default=5.0)
    sw.add_argument("--slippage-bps", type=float, default=2.0)
    sw.add_argument("--qty-pct", type=float, default=1.0)
    sw.add_argument("--leverage", type=float, default=1.0)
    sw.add_argument("--sl-pct", type=float, default=1.2)
    sw.add_argument("--tp-pct", type=float, default=2.4)
    sw.add_argument("--trail-pct", dest="trail_pct", type=float, default=0.8)
    sw.add_argument(
        "--sort",
        choices=["pnl", "sharpe", "winrate", "dd", "return"],
        default="pnl",
        help="Rank column (default: pnl)",
    )
    sw.add_argument("--top", type=int, default=0, help="Only show top N (0 = all)")
    sw.add_argument("--min-trades", type=int, default=1)
    sw.add_argument("--profitable-only", action="store_true")
    sw.add_argument("--csv", default=None, help="Optional path to save leaderboard CSV")
    sw.add_argument("--base-url", default=None)
    sw.add_argument("--api-key", default=None)
    sw.add_argument("--api-secret", default=None)
    swv = sw.add_mutually_exclusive_group()
    swv.add_argument("--live", dest="live", action="store_true", default=None,
                     help="Pull history from production venue (default).")
    swv.add_argument("--testnet", dest="live", action="store_false",
                     help="Force testnet endpoint (limited history).")

    tk = sub.add_parser("tasks", help="Manage background tasks / scheduled jobs")
    tsub = tk.add_subparsers(dest="tcmd", required=True)
    tsub.add_parser("list", help="List all active background tasks")
    tsub.add_parser("catalog", help="List all available task scripts, descriptions, and parameter inputs")
    tsub.add_parser("scripts", help="List all available task scripts, descriptions, and parameter inputs")

    tp = tsub.add_parser("pause", help="Pause background task")
    tp.add_argument("--id", type=int, default=None, help="Task ID")
    tp.add_argument("--all", action="store_true", help="Pause all background tasks")

    tr = tsub.add_parser("resume", help="Resume background task")
    tr.add_argument("--id", type=int, default=None, help="Task ID")
    tr.add_argument("--all", action="store_true", help="Resume all background tasks")

    tsub.add_parser("pause-all", help="Pause all background tasks")
    tsub.add_parser("resume-all", help="Resume all background tasks")

    tl = tsub.add_parser("logs", help="View background task execution logs")
    tl.add_argument("--id", type=int, required=True, help="Task ID")
    tl.add_argument("--limit", type=int, default=50, help="Log limit")

    trm = tsub.add_parser("rm", help="Remove background task")
    trm.add_argument("--id", type=int, required=True, help="Task ID")

    tadd = tsub.add_parser("add", help="Add new background task")
    tadd.add_argument("--name", required=True, help="Task name")
    tadd.add_argument("--script", required=True, help="Script name in delta_bt/tasks/")
    tadd.add_argument("--interval", type=int, default=900, help="Interval in seconds")
    tadd.add_argument("--desc", default="", help="Description")
    tadd.add_argument("--params", default="{}", help="JSON params")

    trn = tsub.add_parser("run-now", help="Run background task immediately once")
    trn.add_argument("--id", type=int, required=True, help="Task ID")

    ted = tsub.add_parser("edit", help="Edit existing background task parameters or status")
    ted.add_argument("--id", type=int, required=True, help="Task ID")
    ted.add_argument("--interval", type=int, default=None, help="New interval in seconds")
    ted.add_argument("--name", default=None, help="New task name")
    ted.add_argument("--status", choices=["running", "paused"], default=None, help="New status")
    ted.add_argument("--params", default=None, help="New params as JSON string (replaces existing)")

    # PnL & Analytics
    pn = sub.add_parser("pnl", help="Show portfolio PnL summary, win rate, and ASCII equity chart")
    pn.add_argument("--days", type=int, default=30, help="Number of daily breakdown rows to show")

    pns = sub.add_parser("pnl-strategy", help="Show performance breakdown per strategy")

    # Terminal Monitor & Emergency Kill-switch
    mn = sub.add_parser("monitor", help="Launch live terminal console PnL dashboard")
    mn.add_argument("--interval", type=int, default=3, help="Terminal refresh interval in seconds")

    db = sub.add_parser("dashboard", help="Launch live terminal console PnL dashboard")
    db.add_argument("--interval", type=int, default=3, help="Terminal refresh interval in seconds")

    bca = sub.add_parser("bot-close-all", help="Emergency CLI kill-switch: close all open exchange positions immediately")

    return p





def _run_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def _resolve_urls(a, live: bool):
    base = getattr(a, "base_url", None) or (DEFAULT_BASE_LIVE if live else DEFAULT_BASE_DEMO)
    ws = getattr(a, "ws_url", None) or (DEFAULT_WS_LIVE if live else DEFAULT_WS_DEMO)
    return base, ws


def _resolve_keys(a, live: bool):
    """Pick API key/secret. CLI flag > venue-specific env > generic env.

    Live venue  → DELTA_LIVE_API_KEY / DELTA_LIVE_API_SECRET
    Testnet     → DELTA_TESTNET_API_KEY / DELTA_TESTNET_API_SECRET
    Fallback    → DELTA_API_KEY / DELTA_API_SECRET (back-compat)
    """
    prefix = "DELTA_LIVE" if live else "DELTA_TESTNET"
    key = (
        getattr(a, "api_key", None)
        or os.getenv(f"{prefix}_API_KEY")
        or os.getenv("DELTA_API_KEY", "")
    )
    sec = (
        getattr(a, "api_secret", None)
        or os.getenv(f"{prefix}_API_SECRET")
        or os.getenv("DELTA_API_SECRET", "")
    )
    return key, sec


def _mk_cfg(a) -> RunConfig:
    return RunConfig(
        strategy=a.strategy,
        symbol=a.symbol,
        resolution=a.resolution,
        capital=a.capital,
        params=a.params,
        start=getattr(a, "start", None),
        end=getattr(a, "end", None),
        fee_bps=a.fee_bps,
        slippage_bps=a.slippage_bps,
        qty_pct=a.qty_pct,
        sl_pct=a.sl_pct,
        tp_pct=a.tp_pct,
        trail_pct=a.trail_pct,
        leverage=a.leverage,
        adx_filter=getattr(a, "adx_filter", False),
        adx_len=getattr(a, "adx_len", 14),
        adx_trend_min=getattr(a, "adx_trend_min", 20.0),
        adx_range_max=getattr(a, "adx_range_max", 20.0),
        adx_exit_on_flip=getattr(a, "adx_exit_on_flip", False),
        adx_tighten_trail_on_flip=getattr(a, "adx_tighten_trail_on_flip", 0.0),
        record_diagnostics=getattr(a, "diagnostics", False),
    )


def cmd_backtest(a) -> int:
    if a.days is not None:
        # Delta rejects an `end` that is in the future (even by a second, due to
        # local clock skew), so back the window off by 2 minutes.
        a.end = datetime.now(tz=timezone.utc) - timedelta(minutes=2)
        a.start = a.end - timedelta(days=a.days)
    if not (a.start and a.end):
        print("provide --days OR both --start and --end", file=sys.stderr)
        return 2
    # Normalize any naive datetimes to UTC and clamp end to "now - 60s".
    now_utc = datetime.now(tz=timezone.utc)
    if a.start.tzinfo is None:
        a.start = a.start.replace(tzinfo=timezone.utc)
    if a.end.tzinfo is None:
        a.end = a.end.replace(tzinfo=timezone.utc)
    max_end = now_utc - timedelta(seconds=60)
    if a.end > max_end:
        a.end = max_end
    if a.end <= a.start:
        print("invalid range: end must be after start", file=sys.stderr)
        return 2

    # Backtest is read-only — default to LIVE venue (full history).
    # Testnet has only days-to-weeks of candles, so use --testnet only if asked.
    live = True if a.live is None else a.live
    base, _ = _resolve_urls(a, live=live)
    key, sec = _resolve_keys(a, live=live)
    client = DeltaClient(base, key, sec)
    print(f"[hist] {a.symbol} {a.resolution} {a.start} → {a.end}  (venue={base})")
    bars = load_history(client, a.symbol, a.resolution, a.start, a.end)
    print(f"[hist] {len(bars)} bars loaded")
    if not bars:
        msg = "no data returned; check symbol/timeframe/dates"
        if not live:
            msg += " — testnet has very limited history; retry without --testnet"
        print(msg, file=sys.stderr)
        return 2

    cfg = _mk_cfg(a)
    strat = load_strategy(a.strategy, a.params)
    pf = run_backtest(bars, strat, cfg)

    out = os.path.join(a.reports_dir, _run_id("backtest"))
    write_report(
        pf,
        out,
        {
            "mode": "backtest",
            "strategy": a.strategy,
            "symbol": a.symbol,
            "resolution": a.resolution,
            "start": a.start.isoformat(),
            "end": a.end.isoformat(),
            "params": a.params,
            "sl_pct": a.sl_pct,
            "tp_pct": a.tp_pct,
            "trail_pct": a.trail_pct,
            "leverage": a.leverage,
        },
    )
    return 0


def _paper_or_live(a, *, live_venue: bool) -> int:
    if getattr(a, "single_run", False):
        if live_venue:
            a.venue = "live"
        else:
            a.venue = "paper_live" if getattr(a, "live_orders", False) else "paper"
        a.size = getattr(a, "live_qty", 1)
        a.warmup_bars = 400
        a.dry_run = False
        a.reduce_only = False
        a.i_understand_live = getattr(a, "i_understand", False)
        return cmd_trade(a)

    # Paper honors --live / --testnet for choosing the market-data venue.
    # (Live-venue command always uses production.)
    if live_venue:
        stream_live = True
    else:
        stream_live = True if getattr(a, "live", None) is None else bool(a.live)

    base, ws = _resolve_urls(a, live=stream_live)
    cfg = _mk_cfg(a)
    strat = load_strategy(a.strategy, a.params)

    live_orders = live_venue or getattr(a, "live_orders", False)
    client = None
    if live_orders:
        # Orders always go to the demo venue for `paper --live-orders`, and to
        # production for the `live` command.
        key, sec = _resolve_keys(a, live=live_venue)
        if not (key and sec):
            print(
                "live orders need api key/secret (--api-key/--api-secret or "
                "DELTA_LIVE_API_KEY / DELTA_TESTNET_API_KEY env)",
                file=sys.stderr,
            )
            return 2
        order_base, _ = _resolve_urls(a, live=live_venue)
        client = DeltaClient(order_base, key, sec)

    # Warn users when the resolution means they'll wait a long time for the
    # first bar to close (and much longer for a strategy signal).
    slow = {"15m", "30m", "1h", "2h", "4h", "6h", "1d"}
    if a.resolution in slow:
        print(
            f"[paper] note: --timeframe {a.resolution} — first bar only emits "
            f"when that bucket closes on the exchange. For quick smoke-tests "
            f"use --timeframe 1m.",
            file=sys.stderr,
        )
    print(
        f"[paper] venue={'live' if stream_live else 'testnet'}  ws={ws}  "
        f"symbol={a.symbol}  tf={a.resolution}  "
        f"orders={'ON' if live_orders else 'sim'}"
    )

    pf = run_paper(
        ws_url=ws,
        strat=strat,
        cfg=cfg,
        duration_s=getattr(a, "duration", None),
        live_orders=live_orders,
        client=client,
        live_qty_contracts=getattr(a, "live_qty", 1),
    )
    mode = (
        "live" if live_venue else ("paper-live-orders" if live_orders else "paper-sim")
    )
    out = os.path.join(a.reports_dir, _run_id(mode))
    write_report(
        pf,
        out,
        {
            "mode": mode,
            "strategy": a.strategy,
            "symbol": a.symbol,
            "resolution": a.resolution,
            "start": None,
            "end": None,
            "params": a.params,
            "sl_pct": a.sl_pct,
            "tp_pct": a.tp_pct,
            "trail_pct": a.trail_pct,
            "leverage": a.leverage,
            "base_url": base,
        },
    )
    return 0


def cmd_paper(a) -> int:
    return _paper_or_live(a, live_venue=False)


def cmd_live(a) -> int:
    if not a.i_understand:
        print("Refusing to trade real funds without --i-understand", file=sys.stderr)
        return 2
    print(f"[live] PRODUCTION venue — {DEFAULT_BASE_LIVE}  symbol={a.symbol}")
    return _paper_or_live(a, live_venue=True)


def cmd_list(_a) -> int:
    reg = discover_strategies()
    if not reg:
        print("(no strategies found)")
        return 0
    print("Available strategies:")
    for name, cls in sorted(reg.items()):
        doc = (cls.__doc__ or "").strip().splitlines()[0] if cls.__doc__ else ""
        print(f"  - {name:<20} {doc}")
    return 0


def _fmt(v, spec=".2f"):
    if v is None:
        return "-"
    try:
        return format(v, spec)
    except Exception:
        return str(v)


def cmd_runs(a) -> int:
    from .store.db import list_runs

    rows = list_runs(limit=a.limit, strategy=a.strategy, symbol=a.symbol)
    if not rows:
        print("(no runs stored yet)")
        return 0
    hdr = (
        f"{'run_id':38} {'strategy':22} {'sym':8} {'tf':5} {'trd':>4} "
        f"{'wr%':>6} {'pnl':>10} {'ret%':>7} {'dd%':>7} {'sharpe':>7}"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(
            f"{r['run_id']:38} {r['strategy']:22} {r['symbol']:8} "
            f"{r['resolution']:5} {r['trades'] or 0:>4} "
            f"{_fmt(r['win_rate_pct']):>6} {_fmt(r['net_pnl']):>10} "
            f"{_fmt(r['return_pct']):>7} {_fmt(r['max_dd_pct']):>7} "
            f"{_fmt(r['sharpe']):>7}"
        )
    return 0


def cmd_compare(a) -> int:
    from .store.db import compare_strategies

    rows = compare_strategies(symbol=a.symbol)
    if not rows:
        print("(no runs stored yet)")
        return 0
    hdr = (
        f"{'strategy':24} {'runs':>4} {'avg_pnl':>10} {'avg_ret%':>9} "
        f"{'wr%':>6} {'pf':>6} {'dd%':>7} {'sharpe':>7} {'trades':>7}"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(
            f"{r['strategy']:24} {r['runs']:>4} "
            f"{_fmt(r['avg_net_pnl']):>10} {_fmt(r['avg_return_pct']):>9} "
            f"{_fmt(r['avg_win_rate']):>6} {_fmt(r['avg_pf']):>6} "
            f"{_fmt(r['avg_max_dd']):>7} {_fmt(r['avg_sharpe']):>7} "
            f"{r['total_trades'] or 0:>7}"
        )
    return 0


def cmd_plot(a) -> int:
    from .store.plot import plot_runs, resolve_run_ids

    ids = resolve_run_ids(a.run_id, strategy=a.strategy, symbol=a.symbol, last=a.last)
    if not ids:
        print("(no runs to plot)")
        return 0
    out = plot_runs(ids, a.out, normalize=a.normalize, title=a.title, markers=a.markers)

    print(f"[plot] {len(ids)} run(s) rendered → {out}")
    for i in ids:
        print(f"  · {i}")
    return 0


def cmd_scan(a) -> int:
    """Run every registered strategy against one symbol/timeframe and rank them."""
    # --- resolve window (same clamping rules as cmd_backtest) ---
    if a.start and a.end:
        start, end = a.start, a.end
    else:
        end = datetime.now(tz=timezone.utc) - timedelta(minutes=2)
        start = end - timedelta(days=a.days)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if end <= start:
        print("invalid range", file=sys.stderr)
        return 2

    live = True if a.live is None else a.live
    base, _ = _resolve_urls(a, live=live)
    key, sec = _resolve_keys(a, live=live)
    client = DeltaClient(base, key, sec)
    print(
        f"[scan] {a.symbol} @ {a.resolution}  {start.date()} → {end.date()}  "
        f"(SL {a.sl_pct}% / TP {a.tp_pct}% / trail {a.trail_pct}% / lev {a.leverage}x)  "
        f"venue={base}"
    )

    # --- pull history ONCE and reuse for every strategy ---
    bars = load_history(client, a.symbol, a.resolution, start, end)
    if not bars:
        msg = "no data returned; check symbol/timeframe/dates"
        if not live:
            msg += " — testnet has very limited history; retry without --testnet"
        print(msg, file=sys.stderr)
        return 2
    print(
        f"[scan] {len(bars)} bars loaded — running {len(discover_strategies())} strategies"
    )

    cfg = RunConfig(
        strategy="_scan",
        symbol=a.symbol,
        resolution=a.resolution,
        capital=a.capital,
        params={},
        start=start,
        end=end,
        fee_bps=a.fee_bps,
        slippage_bps=a.slippage_bps,
        qty_pct=a.qty_pct,
        sl_pct=a.sl_pct,
        tp_pct=a.tp_pct,
        trail_pct=a.trail_pct,
        leverage=a.leverage,
        adx_filter=a.adx_filter,
        adx_len=a.adx_len,
        adx_trend_min=a.adx_trend_min,
        adx_range_max=a.adx_range_max,
        adx_exit_on_flip=a.adx_exit_on_flip,
        adx_tighten_trail_on_flip=a.adx_tighten_trail_on_flip,
    )

    from .reports.report import summarize

    results = []
    for name in sorted(discover_strategies().keys()):
        try:
            strat = load_strategy(name, {})
            pf = run_backtest(bars, strat, cfg)
            s = summarize(pf)
            results.append({"strategy": name, "summary": s, "pf": pf})
            if a.save:
                out = os.path.join(a.reports_dir, _run_id(f"scan_{name}"))
                write_report(
                    pf,
                    out,
                    {
                        "mode": "backtest",
                        "strategy": name,
                        "symbol": a.symbol,
                        "resolution": a.resolution,
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                        "params": {},
                        "sl_pct": a.sl_pct,
                        "tp_pct": a.tp_pct,
                        "trail_pct": a.trail_pct,
                        "leverage": a.leverage,
                    },
                )
            print(
                f"  ✓ {name:<24} ret {s['return_pct']:>7.2f}%  "
                f"trades {s['trades']:>4}  wr {s['win_rate_pct']:>5.1f}%  "
                f"pf {s['profit_factor']:>5.2f}  dd {s['max_drawdown_pct']:>6.2f}%"
            )
        except Exception as e:
            print(f"  ✗ {name:<24} ERROR: {e}")

    # --- rank ---
    ranked = [r for r in results if r["summary"]["trades"] >= a.min_trades]
    if a.profitable_only:
        ranked = [r for r in ranked if r["summary"]["return_pct"] > 0]
    ranked.sort(key=lambda r: r["summary"]["return_pct"], reverse=True)
    if a.top and a.top > 0:
        ranked = ranked[: a.top]

    from .pnl_analytics import render_box_table, format_pnl, format_pct

    headers = ["Rank", "Strategy", "Return %", "Net PnL ($)", "Trades", "WinRate%", "PF", "Max DD%", "Sharpe", "Profitable"]
    table_rows = []
    for i, r in enumerate(ranked, 1):
        s = r["summary"]
        flag = "YES 🟢" if s["return_pct"] > 0 else "no 🔴"
        table_rows.append([
            str(i),
            r["strategy"],
            format_pct(s["return_pct"]),
            format_pnl(s["net_pnl"]),
            str(s["trades"]),
            f"{s['win_rate_pct']:.1f}%",
            f"{s['profit_factor']:.2f}",
            f"{s['max_drawdown_pct']:.2f}%",
            f"{s['sharpe']:.2f}",
            flag
        ])

    title = f"LEADERBOARD — {a.symbol} @ {a.resolution} ({len(ranked)} strategies)"
    print("\n" + render_box_table(headers, table_rows, title=title))
    profitable = [r for r in results if r["summary"]["return_pct"] > 0]
    print(
        f"\nProfitable: {len(profitable)} / {len(results)}   "
        f"(SL/TP/trail active on all runs — tune with --sl-pct / --tp-pct / --trail-pct)"
    )
    if not a.save:
        print(
            "(runs NOT saved to SQLite — pass --save to persist for `runs`/`plot`/dashboard)"
        )
    print()
    return 0


def cmd_serve(a) -> int:
    from .server import serve

    return serve(host=a.host, port=a.port, db_path=a.db)


def cmd_plot_diag(a) -> int:
    run_dir = a.run_dir or (os.path.join(a.reports_dir, a.run_id) if a.run_id else None)
    if not run_dir:
        print("plot-diag needs --run-dir OR --run-id", file=sys.stderr)
        return 2
    if not os.path.isdir(run_dir):
        print(f"not a directory: {run_dir}", file=sys.stderr)
        return 2
    csv_path = os.path.join(run_dir, "diagnostics.csv")
    if not os.path.exists(csv_path):
        print(
            f"no diagnostics.csv in {run_dir} — re-run the backtest with --diagnostics",
            file=sys.stderr,
        )
        return 2
    if a.csv_only:
        print(csv_path)
        return 0
    from .store.diag_plot import plot_diagnostics

    out = plot_diagnostics(run_dir, out_path=a.out, title=a.title)
    print(f"[plot-diag] wrote {out}")
    print(f"           source: {csv_path}")
    return 0


def cmd_rank_universe(a) -> int:
    from .scanner.rank_universe import rank_universe, write_universe_csv

    base = a.base_url or (DEFAULT_BASE_LIVE if a.live else DEFAULT_BASE_DEMO)
    key, sec = _resolve_keys(a, live=bool(a.live))
    client = DeltaClient(base, key, sec)
    print(
        f"[rank-universe] venue={base}  tf={a.resolution}  "
        f"min_turnover=${a.min_turnover_usd:,.0f}  regime_bias={a.regime_bias}"
    )
    rows = rank_universe(
        client,
        resolution=a.resolution,
        lookback_bars=a.lookback_bars,
        adx_len=a.adx_len,
        trend_min=a.adx_trend_min,
        range_max=a.adx_range_max,
        min_turnover_usd=a.min_turnover_usd,
        max_funding_pct=a.max_funding_pct,
        atr_min_pct=a.atr_min_pct,
        atr_max_pct=a.atr_max_pct,
        quote_symbol_suffix=a.quote_suffix,
        contract_types=a.contract_types,
        regime_bias=a.regime_bias,
        top=a.top,
        workers=a.workers,
    )
    if not rows:
        print(
            "(no symbols survived the filters — loosen --min-turnover-usd "
            "or --atr-min-pct/--atr-max-pct)"
        )
        return 0
    out = write_universe_csv(rows, a.out)
    hdr = (
        f"{'#':>3}  {'symbol':<12} {'score':>6} {'regime':<7} "
        f"{'turnover$M':>10} {'adx':>5} {'atr%':>5} {'bbw%':>5} "
        f"{'ret%':>6} {'rs_btc':>6} {'fund%':>6}"
    )
    print(hdr)
    print("-" * len(hdr))
    for i, s in enumerate(rows, 1):
        print(
            f"{i:>3}  {s.symbol:<12} {s.score:>6.2f} {s.regime:<7} "
            f"{s.turnover_usd / 1e6:>10.1f} "
            f"{_fmt(s.adx, '.1f'):>5} {_fmt(s.atr_pct, '.2f'):>5} "
            f"{_fmt(s.bb_width_pct, '.2f'):>5} "
            f"{_fmt(s.ret_pct, '.2f'):>6} {_fmt(s.rs_vs_btc, '.2f'):>6} "
            f"{s.funding_pct:>6.3f}"
        )
    print(f"\n[rank-universe] wrote {out}  ({len(rows)} rows)")
    return 0


def cmd_balance(a) -> int:
    live = True if a.live is None else a.live
    base, _ = _resolve_urls(a, live=live)
    key, sec = _resolve_keys(a, live=live)
    client = DeltaClient(base, key, sec)
    balances = client.balances()
    print(json.dumps(balances, indent=2))
    return 0


def cmd_order(a) -> int:
    order_type = {"market": "market_order", "limit": "limit_order"}.get(a.order_type, a.order_type)
    if order_type == "limit_order" and not a.limit_price:
        print("--limit-price required for limit orders", file=sys.stderr)
        return 2
    if a.venue in ("paper","paper_live"):
        # Simulated fill using recent public candles (no credentials required).
        base = os.getenv("DELTA_TESTNET_BASE_URL", "https://cdn-ind.testnet.deltaex.org")
        client = DeltaClient(base, "", "")
        end = datetime.now(tz=timezone.utc) - timedelta(seconds=30)
        start = end - timedelta(minutes=15)
        bars = load_history(client, a.symbol, "1m", start, end)
        mark = float(bars[-1].close) if bars else None
        fill = float(a.limit_price) if order_type == "limit_order" else mark
        print(json.dumps({
            "paper": True, "venue": "paper", "symbol": a.symbol, "side": a.side,
            "size": int(a.size), "order_type": order_type,
            "limit_price": a.limit_price, "mark_price": mark, "fill_price": fill,
            "reduce_only": bool(a.reduce_only), "state": "filled" if fill else "rejected",
        }, indent=2, default=str))
        return 0
    live = a.venue == "live"
    if live and not a.i_understand_live:
        print("Refusing live order without --i-understand-live", file=sys.stderr)
        return 2
    base, _ = _resolve_urls(a, live=live)
    key, sec = _resolve_keys(a, live=live)
    if not (key and sec):
        print(
            f"missing credentials for {a.venue}: set DELTA_{a.venue.upper()}_API_KEY / "
            f"DELTA_{a.venue.upper()}_API_SECRET",
            file=sys.stderr,
        )
        return 2
    client = DeltaClient(base, key, sec)
    product = client.get_product(a.symbol)
    result = client.place_order(
        int(product["id"]),
        int(a.size),
        a.side,
        order_type=order_type,
        limit_price=str(a.limit_price) if a.limit_price is not None else None,
        reduce_only=a.reduce_only,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_trade(a) -> int:
    paper = a.venue in ("paper","paper_live")
    live = a.venue == "live"
    if live and not a.i_understand_live:
        print("Refusing live strategy trade without --i-understand-live", file=sys.stderr)
        return 2
    if paper:
        # Public candles only — no credentials required.
        base = os.getenv("DELTA_TESTNET_BASE_URL", "https://cdn-ind.testnet.deltaex.org")
        key, sec = "", ""
    else:
        base, _ = _resolve_urls(a, live=live)
        key, sec = _resolve_keys(a, live=live)
    client = DeltaClient(base, key, sec)

    step_seconds = {
        "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
        "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "1d": 86400, "7d": 604800,
    }.get(a.resolution, 900)
    end = datetime.now(tz=timezone.utc) - timedelta(seconds=30)
    start = end - timedelta(seconds=max(2, a.warmup_bars) * step_seconds)
    bars = load_history(client, a.symbol, a.resolution, start, end)
    if len(bars) < 2:
      print("not enough recent candles to evaluate", file=sys.stderr)
      return 2

    strat = load_strategy(a.strategy, a.params)
    if hasattr(strat, "on_start"):
        strat.on_start()
    from .core.strategy import StrategyContext
    from .core.types import Position, Signal
    pos = Position(symbol=a.symbol)
    sig = Signal.FLAT
    for bar in bars:
        sig = strat.on_bar(bar, StrategyContext(pos, 0.0, 0.0))
    if hasattr(strat, "on_stop"):
        strat.on_stop()

    last = bars[-1]
    print(f"[trade] {a.strategy} {a.symbol} {a.resolution} bars={len(bars)} last={last.ts.isoformat()} close={last.close} signal={sig}")
    if sig not in (Signal.BUY, Signal.SELL):
        print("[trade] no BUY/SELL on last bar — no order placed")
        return 0
    side = "buy" if sig == Signal.BUY else "sell"
    if a.dry_run:
        print(f"[trade] dry-run: would place {side} {a.size} {a.symbol} on {a.venue}")
        return 0
    if paper:
        print(json.dumps({
            "paper": True, "venue": "paper", "strategy": a.strategy,
            "symbol": a.symbol, "resolution": a.resolution,
            "side": side, "size": int(a.size), "fill_price": float(last.close),
            "signal": sig.name, "state": "filled",
        }, indent=2, default=str))
        return 0
    if not (key and sec):
        print(
            f"missing credentials for {a.venue}: set DELTA_{a.venue.upper()}_API_KEY / "
            f"DELTA_{a.venue.upper()}_API_SECRET",
            file=sys.stderr,
        )
        return 2
    product = client.get_product(a.symbol)
    result = client.place_order(
        int(product["id"]), int(a.size), side,
        order_type="market_order", reduce_only=a.reduce_only,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_watch(a) -> int:
    from .scheduler import run
    return run(interval_sec=a.interval, once=a.once)


def cmd_deployments(a) -> int:
    from .import deployments as dep
    from .pnl_analytics import render_box_table, format_pnl
    if a.dcmd == "list":
        rows_data = dep.list_deployments(
            status=getattr(a, "status", None),
            venue=getattr(a, "venue", None),
            strategy=getattr(a, "strategy", None),
            symbol=getattr(a, "symbol", None)
        )
        headers = ["ID", "Name", "Venue", "Strategy", "Symbol", "TF", "Status", "Last Signal", "Realized PnL ($)"]
        rows = []
        for r in rows_data:
            pnl_str = format_pnl(r['realized_pnl'])
            rows.append([
                str(r["id"]),
                str(r["name"])[:20],
                str(r["venue"]),
                str(r["strategy"])[:16],
                str(r["symbol"])[:12],
                str(r["resolution"]),
                str(r["status"]),
                str(r["last_signal"] or "-"),
                pnl_str
            ])
        print("\n" + render_box_table(headers, rows, title="BOT DEPLOYMENTS & LIVE TRADING FLEET") + "\n")
        return 0
    if a.dcmd == "add":
        did = dep.add_deployment(
            name=a.name, venue=a.venue, strategy=a.strategy, symbol=a.symbol,
            resolution=a.resolution, size=a.size, params=a.params,
            sl_pct=a.sl_pct, tp_pct=a.tp_pct, trail_pct=a.trail_pct,
            reduce_only=a.reduce_only, interval_sec=a.interval,
            i_understand_live=a.i_understand_live,
        )
        print(f"created deployment #{did}"); return 0
    if a.dcmd == "stop-all" or (a.dcmd == "stop" and getattr(a, "all", False)):
        vf = getattr(a, "venue", None)
        deps = dep.list_deployments(venue=vf)
        count = 0
        for d in deps:
            if d["status"] in ("running", "paused"):
                dep.set_status(d["id"], "stopped", f"stopped via CLI stop-all {vf or ''}".strip())
                count += 1
        msg = f"stopped {count} bot deployment(s)"
        if vf: msg += f" on venue [{vf}]"
        print(msg)
        return 0

    if a.dcmd == "pause-all" or (a.dcmd == "pause" and getattr(a, "all", False)):
        vf = getattr(a, "venue", None)
        deps = dep.list_deployments(venue=vf)
        count = 0
        for d in deps:
            if d["status"] == "running":
                dep.set_status(d["id"], "paused", f"paused via CLI pause-all {vf or ''}".strip())
                count += 1
        msg = f"paused {count} bot deployment(s)"
        if vf: msg += f" on venue [{vf}]"
        print(msg)
        return 0

    if a.dcmd == "resume-all" or (a.dcmd == "resume" and getattr(a, "all", False)):
        vf = getattr(a, "venue", None)
        deps = dep.list_deployments(venue=vf)
        count = 0
        for d in deps:
            if d["status"] == "paused":
                dep.set_status(d["id"], "running", f"resumed via CLI resume-all {vf or ''}".strip())
                count += 1
        msg = f"resumed {count} bot deployment(s)"
        if vf: msg += f" on venue [{vf}]"
        print(msg)
        return 0

    bot_id = getattr(a, "opt_id", None) if getattr(a, "opt_id", None) is not None else getattr(a, "pos_id", None)
    if bot_id is None and hasattr(a, "id"):
        bot_id = a.id

    if bot_id is None and a.dcmd in ("pause", "resume", "stop", "rm", "close"):
        print(f"Deployment ID required for `deployments {a.dcmd}` (e.g. `deployments {a.dcmd} 1` or `--all`)", file=sys.stderr)
        return 1

    if a.dcmd == "pause": dep.set_status(bot_id, "paused", "paused via CLI"); print(f"paused deployment #{bot_id}"); return 0
    if a.dcmd == "resume": dep.set_status(bot_id, "running", "resumed via CLI"); print(f"resumed deployment #{bot_id}"); return 0
    if a.dcmd == "stop": dep.set_status(bot_id, "stopped", "stopped via CLI"); print(f"stopped deployment #{bot_id}"); return 0
    if a.dcmd == "rm":
        try: dep.remove_deployment(bot_id); print(f"removed deployment #{bot_id}"); return 0
        except ValueError as e: print(str(e), file=sys.stderr); return 2
    if a.dcmd == "close":
        print("Use the Trade page 'Close position' action, or `python -m delta_bt order` with --reduce-only.")
        return 0
    if a.dcmd == "edit":
        import json as _ej
        bot_id = getattr(a, "opt_id", None) or getattr(a, "pos_id", None)
        if bot_id is None:
            print("Bot ID required: deployments edit <ID> or --id <ID>", file=sys.stderr)
            return 1
        from .deployments import get_deployment, record_event_full
        row = get_deployment(bot_id)
        if row is None:
            print(f"Bot #{bot_id} not found", file=sys.stderr)
            return 1

        # Build SET clauses only for fields that were actually supplied
        sets, vals, changed = [], [], []

        def _field(col, attr_val, label=None):
            if attr_val is not None:
                sets.append(f"{col} = ?")
                vals.append(attr_val)
                changed.append(f"{label or col} → {attr_val}")

        _field("name",                a.name)
        _field("venue",               a.venue)
        _field("strategy",            a.strategy)
        _field("symbol",              a.symbol)
        _field("resolution",          a.resolution)
        _field("size",                a.size,                "size (lots)")
        _field("sl_pct",              a.sl_pct,              "sl_pct")
        _field("tp_pct",              a.tp_pct,              "tp_pct")
        _field("trail_pct",           a.trail_pct,           "trail_pct")
        _field("trail_activate_pct",  a.trail_activate_pct,  "trail_activate_pct")
        _field("breakeven_after_pct", a.breakeven_after_pct, "breakeven_after_pct")
        _field("leverage",            a.leverage)
        _field("interval_sec",        a.interval,            "interval_sec")
        _field("status",              a.status)

        if a.params is not None:
            try:
                _ej.loads(a.params)   # validate JSON
            except Exception as e:
                print(f"[deployments edit] invalid --params JSON: {e}", file=sys.stderr)
                return 1
            sets.append("params_json = ?")
            vals.append(a.params)
            changed.append(f"params_json → {a.params}")

        if not sets:
            print(f"Nothing to update — pass at least one flag (e.g. --sl-pct 2.0 --size 5)", file=sys.stderr)
            return 1

        with dep.open_db() as db:
            db.execute(
                f"UPDATE deployments SET {', '.join(sets)} WHERE id = ?",
                vals + [bot_id],
            )
        summary = "\n  ".join(changed)
        record_event_full(bot_id, "params_edited",
                          message=f"parameters edited via CLI:\n  {summary}")
        print(f"Updated bot #{bot_id}:\n  {summary}")
        return 0
    return 2


def _venue_client(venue: str) -> DeltaClient:
    live = venue == "live"
    base = DEFAULT_BASE_LIVE if live else DEFAULT_BASE_DEMO
    prefix = "DELTA_LIVE" if live else "DELTA_TESTNET"
    key = os.getenv(f"{prefix}_API_KEY") or os.getenv("DELTA_API_KEY", "")
    sec = os.getenv(f"{prefix}_API_SECRET") or os.getenv("DELTA_API_SECRET", "")
    return DeltaClient(base, key, sec)


def cmd_folio(a) -> int:
    from . import deployments as dep

    from .pnl_analytics import format_pnl
    venues = ["testnet", "live"] if a.venue == "both" else [a.venue]
    snapshot: Dict[str, Any] = {}
    for v in venues:
        entry: Dict[str, Any] = {"balances": [], "positions": [], "error": None}
        try:
            c = _venue_client(v)
            entry["balances"] = c.balances()
            try:
                entry["positions"] = c.positions()
            except Exception as e:  # noqa: BLE001
                entry["positions_error"] = str(e)
        except Exception as e:  # noqa: BLE001
            entry["error"] = str(e)
        snapshot[v] = entry

    # Bot summary (from local DB)
    bots = dep.list_deployments()
    if a.json:
        print(json.dumps({"venues": snapshot, "deployments": [dict(b) for b in bots]},
                         indent=2, default=str))
        return 0

    for v, e in snapshot.items():
        print(f"\n== {v.upper()} ==")
        if e.get("error"):
            print(f"  balances/positions unavailable: {e['error']}")
            continue
        print("  Balances:")
        rows = e["balances"] or []
        if not rows:
            print("    (none)")
        for b in rows:
            asset = b.get("asset_symbol") or b.get("asset", {}).get("symbol", "?")
            bal = b.get("balance") or b.get("available_balance") or 0
            print(f"    {asset:>6}  {float(bal):>16,.4f}")
        print("  Positions:")
        pos = e.get("positions") or []
        if e.get("positions_error"):
            print(f"    (error: {e['positions_error']})")
        if not pos:
            print("    (flat)")
        for p in pos:
            sym = p.get("product_symbol") or p.get("product", {}).get("symbol", "?")
            sz = p.get("size", 0)
            entry_px = p.get("entry_price", "-")
            u = p.get("unrealized_pnl") or p.get("unrealized_margin", 0)
            r = p.get("realized_pnl", 0)
            u_str = format_pnl(float(u)) if u is not None else "-"
            r_str = format_pnl(float(r)) if r is not None else format_pnl(0.0)
            print(f"    {sym:>10}  size={sz}  entry={entry_px}  uPnL={u_str:>19}  rPnL={r_str:>19}")

    print("\n== BOTS ==")
    if not bots:
        print("  (no deployments)")
    else:
        hdr = f"  {'id':>3} {'name':22} {'venue':7} {'strategy':16} {'symbol':10} {'status':8} {'realized':>12}"
        print(hdr); print("  " + "-" * (len(hdr) - 2))
        for b in bots:
            print(f"  {b['id']:>3} {b['name'][:22]:22} {b['venue']:7} {b['strategy'][:16]:16} "
                  f"{b['symbol']:10} {b['status']:8} {format_pnl(b['realized_pnl']):>21}")
    return 0


def cmd_trades(a) -> int:
    from .store.db import connect, list_runs
    from .pnl_analytics import format_pnl

    conds, args = [], []
    if a.run_id:
        conds.append("t.run_id = ?"); args.append(a.run_id)
    if a.strategy:
        conds.append("r.strategy = ?"); args.append(a.strategy)
    if a.symbol:
        conds.append("t.symbol = ?"); args.append(a.symbol)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    q = (f"SELECT t.run_id, r.strategy, t.symbol, t.side, t.qty, "
         f"t.entry_ts, t.entry_price, t.exit_ts, t.exit_price, "
         f"t.pnl, t.fees, t.return_pct "
         f"FROM trades t LEFT JOIN runs r ON r.run_id = t.run_id"
         f"{where} ORDER BY t.exit_ts DESC LIMIT ?")
    args.append(a.limit)
    with connect() as c:
        rows = c.execute(q, args).fetchall()
    if not rows:
        print("(no trades)")
        return 0
    hdr = (f"{'exit_ts':20} {'run_id':30} {'strategy':16} {'sym':8} {'side':4} "
           f"{'qty':>7} {'entry':>10} {'exit':>10} {'pnl':>12} {'ret%':>7}")
    print(hdr); print("-" * len(hdr))
    for r in rows:
        (run_id, strat, sym, side, qty, e_ts, e_px, x_ts, x_px, pnl, fees, ret) = r
        print(f"{(x_ts or '')[:20]:20} {run_id[:30]:30} {(strat or '-')[:16]:16} "
              f"{sym:8} {side:4} {qty:>7.3f} {e_px:>10.2f} {(x_px or 0):>10.2f} "
              f"{format_pnl(pnl):>21} {_fmt(ret):>7}")
    return 0


def cmd_run_show(a) -> int:
    from .store.db import get_run
    from .pnl_analytics import format_pnl
    r = get_run(a.run_id)
    if not r:
        print(f"run_id not found: {a.run_id}", file=sys.stderr); return 2
    print(f"Run  {r['run_id']}  {r['strategy']} {r['symbol']} {r['resolution']}  mode={r['mode']}")
    print(f"     trades={r['trades']}  wr={_fmt(r['win_rate_pct'])}%  "
          f"pnl={format_pnl(r['net_pnl'])}  ret%={_fmt(r['return_pct'])}  "
          f"dd%={_fmt(r['max_dd_pct'])}  sharpe={_fmt(r['sharpe'])}")
    trades = r.get("trades") or []
    print(f"\nTrades ({len(trades)}):")
    hdr = f"{'#':>4} {'side':4} {'qty':>7} {'entry_ts':20} {'entry':>10} {'exit_ts':20} {'exit':>10} {'pnl':>12} {'ret%':>7}"
    print(hdr); print("-" * len(hdr))
    for i, t in enumerate(trades[: a.limit_trades], 1):
        print(f"{i:>4} {t['side']:4} {t['qty']:>7.3f} {(t['entry_ts'] or '')[:20]:20} "
              f"{t['entry_price']:>10.2f} {(t['exit_ts'] or '')[:20]:20} "
              f"{(t['exit_price'] or 0):>10.2f} {format_pnl(t['pnl']):>21} "
              f"{_fmt(t['return_pct']):>7}")
    return 0


def cmd_activity(a) -> int:
    from . import deployments as dep
    from .pnl_analytics import format_pnl

    if a.id is not None:
        targets = [a.id]
    else:
        targets = [r["id"] for r in dep.list_deployments()]
    if not targets:
        print("(no deployments)"); return 0
    hdr = f"{'dep':>3} {'ts':20} {'kind':8} {'order_id':16} {'pnl':>12} message"
    print(hdr); print("-" * 100)
    for did in targets:
        for ev in dep.get_events(did, limit=a.limit):
            if a.kind and ev["kind"] != a.kind:
                continue
            pnl_str = format_pnl(ev['pnl']) if ev['pnl'] is not None else "-"
            print(f"{did:>3} {(ev['ts'] or '')[:20]:20} {ev['kind']:8} "
                  f"{(ev['order_id'] or '-'):16} {pnl_str:>21} {ev['message'] or ''}")
    return 0


def cmd_bots(a) -> int:
    from .deployments import list_deployments as _list
    from .pnl_analytics import render_box_table, format_pnl
    status_filter = getattr(a, "status", None)
    if not a.all and status_filter is None:
        status_filter = "running"
    rows_data = _list(
        status=status_filter,
        venue=getattr(a, "venue", None),
        strategy=getattr(a, "strategy", None),
        symbol=getattr(a, "symbol", None)
    )
    if not rows_data:
        print("(no bots)"); return 0
    headers = ["ID", "Status", "Venue", "Strategy", "Symbol", "TF", "Size", "Ticks", "Pos", "Realized PnL ($)", "Last Tick", "Signal"]
    rows = []
    for r in rows_data:
        pos = r["open_side"] or "-"
        rows.append([
            str(r["id"]),
            str(r["status"]),
            str(r["venue"]),
            str(r["strategy"])[:18],
            str(r["symbol"]),
            str(r["resolution"]),
            f"{float(r['size']):.4f}",
            str(int(r["ticks"] or 0)),
            pos,
            format_pnl(r["realized_pnl"]),
            str((r["last_tick_at"] or "-")[:19]),
            str(r["last_signal"] or "-")
        ])
    print("\n" + render_box_table(headers, rows, title="RUNNING TRADING BOTS FLEET") + "\n")
    return 0


def cmd_bot_show(a) -> int:
    from .deployments import get_deployment, get_events
    bot_id = a.opt_id if a.opt_id is not None else a.pos_id
    if bot_id is None:
        print("Bot ID required (e.g. `python -m delta_bt bot-show 1` or `--id 1`)", file=sys.stderr)
        return 1
    r = get_deployment(bot_id)
    if not r:
        print(f"bot #{bot_id} not found"); return 1
    for k in ("id", "name", "status", "venue", "strategy", "symbol", "resolution",
              "size", "sl_pct", "tp_pct", "trail_pct", "interval_sec",
              "open_side", "open_qty", "open_price",
              "realized_pnl", "ticks", "last_signal", "last_tick_at",
              "last_error", "created_at", "started_at", "stopped_at"):
        print(f"{k:>18}: {r[k]}")
    print(f"{'params_json':>18}: {r['params_json']}")
    print("\nrecent events:")
    for ev in get_events(bot_id, a.limit):
        pnl = "" if ev["pnl"] is None else f"pnl={ev['pnl']:.4f}"
        print(f"  {ev['ts'][:19]}  {ev['kind']:<10} {pnl} {ev['message'] or ''}")
    return 0


def cmd_bot_events(a) -> int:
    import json as _json
    from .deployments import get_events
    bot_id = a.opt_id if a.opt_id is not None else a.pos_id
    if bot_id is None:
        print("Bot ID required (e.g. `python -m delta_bt bot-events 1` or `--id 1`)", file=sys.stderr)
        return 1
    evs = get_events(bot_id, a.limit)
    out = []
    for e in evs:
        row = {k: e[k] for k in e.keys()}
        if a.kind and dict(row).get("kind") != a.kind:
            continue
        out.append(row)
    print(_json.dumps(out, indent=2, default=str))
    return 0


def cmd_db_info(a) -> int:
    import json as _json
    from .store.db import db_info
    info = db_info()
    if a.json:
        print(_json.dumps(info, indent=2)); return 0
    print(f"path         : {info['path']}")
    print(f"size         : {info['size_mb']} MB ({info['size_bytes']} B)")
    print(f"journal_mode : {info['journal_mode']}")
    print("tables       :")
    for t in info["tables"]:
        print(f"  {t:<24} {info['counts'].get(t, '?'):>8} rows")
    return 0


def cmd_db_path(_a) -> int:
    from .store.db import _resolve_db
    print(_resolve_db())
    return 0


def cmd_db_vacuum(_a) -> int:
    from .store.db import vacuum_db
    r = vacuum_db()
    print(f"vacuumed {r['path']}: {r['before_bytes']} -> {r['after_bytes']} B "
          f"(reclaimed {r['reclaimed_bytes']} B)")
    return 0


def cmd_db_clear(a) -> int:
    from .store.db import clear_table
    if not a.yes:
        ans = input(f"clear table '{a.table}'? [y/N]: ").strip().lower()
        if ans != "y":
            print("aborted"); return 1
def cmd_factory_reset(a) -> int:
    """Master factory reset: clear database, stop active bots, reset background tasks, and clean reports."""
    if not a.yes:
        ans = input("⚠️ Are you sure you want to FACTORY RESET the entire app for a new user? [y/N]: ").strip().lower()
        if ans != "y":
            print("aborted"); return 1

    from .store.db import clear_table, list_background_tasks
    import glob

    # 1. Clear database tables
    r = clear_table("all")
    
    # 2. Re-seed fresh default background tasks
    list_background_tasks()

    # 3. Clean reports folder
    report_files = glob.glob("./reports/**/*.csv", recursive=True)
    for f in report_files:
        try:
            os.remove(f)
        except Exception:
            pass

    C_GREEN = "\033[1;32m"
    C_BOLD = "\033[1m"
    C_RESET = "\033[0m"

    print("\n" + f"{C_BOLD}{C_GREEN}✨ System Factory Reset Complete!{C_RESET}")
    print("  • Database cleared & re-indexed")
    print("  • Deployments & active bots purged")
    print("  • Background tasks reset to default")
    print("  • Reports & temporary files cleaned")
    print(f"  • {C_BOLD}Ready for fresh new user setup!{C_RESET}\n")
    return 0


def cmd_auto_deploy(a) -> int:
    """Smart scanner orchestrator: rank universe -> sweep top coins -> add deployments"""
    import subprocess
    import csv
    import os
    
    target_venue = a.venue if a.venue else ("live" if a.live else "testnet")
    use_live_data = target_venue in ("live", "paper_live") or a.live

    symbols = []
    
    if getattr(a, "symbol", None):
        print(f"[auto-deploy] Target symbol specified: {a.symbol} (skipping market scan)")
        symbols = [a.symbol]
    else:
        print(f"[auto-deploy] Scanning market for top {a.top} assets over last {a.days} days (target venue: {target_venue})...")
        cmd_ru = [
            sys.executable, "-m", "delta_bt", "rank-universe",
            "--top", str(a.top),
            "--lookback-bars", str(max(24, a.days * 24)),
            "--min-turnover-usd", "1000000" if use_live_data else "10000",
            "--resolution", "1h"
        ]
        if use_live_data:
            cmd_ru.append("--live")
            
        try:
            subprocess.run(cmd_ru, check=True)
        except subprocess.CalledProcessError:
            print("[auto-deploy] rank-universe failed.", file=sys.stderr)
            return 1
    
        try:
            with open("./reports/universe/universe.csv", "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    symbols.append(row["symbol"])
        except FileNotFoundError:
            print("[auto-deploy] Failed to read universe.csv", file=sys.stderr)
            return 1

    if not symbols:
        print("[auto-deploy] No symbols found to deploy on.")
        return 0

    for symbol in symbols:
        print(f"\n[auto-deploy] Sweeping strategies for {symbol} @ {a.resolution} over last {a.days} days (SL: {a.sl_pct}% / TP: {a.tp_pct}% / Trail: {a.trail_pct}%)...")
        report_path = f"./reports/sweep/{symbol}.csv"
        cmd_sw = [
            sys.executable, "-m", "delta_bt", "sweep",
            "--symbol", symbol,
            "--resolution", a.resolution,
            "--days", str(a.days),
            "--sl-pct", str(a.sl_pct),
            "--tp-pct", str(a.tp_pct),
            "--trail-pct", str(a.trail_pct),
            "--csv", report_path
        ]
        if use_live_data:
            cmd_sw.append("--live")
        else:
            cmd_sw.append("--testnet")
            
        try:
            subprocess.run(cmd_sw, check=True)
        except subprocess.CalledProcessError:
            print(f"[auto-deploy] sweep failed for {symbol}.", file=sys.stderr)
            continue
            
        best_strategy = None
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                if rows:
                    best_strategy = rows[0]["strategy"]
        except FileNotFoundError:
            pass
            
        if not best_strategy:
            print(f"[auto-deploy] No profitable strategy found for {symbol}.")
            continue
            
        print(f"[auto-deploy] Best strategy for {symbol} is {best_strategy}. Deploying to [{target_venue}]...")
        
        cmd_add = [
            sys.executable, "-m", "delta_bt", "deployments", "add",
            "--name", f"Auto {symbol}",
            "--venue", target_venue,
            "--strategy", best_strategy,
            "--symbol", symbol,
            "--resolution", a.resolution,
            "--size", str(a.size),
            "--sl-pct", str(a.sl_pct),
            "--tp-pct", str(a.tp_pct),
            "--trail-pct", str(a.trail_pct)
        ]
        if target_venue == "live":
            cmd_add.append("--i-understand-live")
        
        try:
            subprocess.run(cmd_add, check=True)
            print(f"[auto-deploy] Successfully deployed {best_strategy} on {symbol} [{target_venue}].")
        except subprocess.CalledProcessError:
            print(f"[auto-deploy] deployment failed for {symbol}.", file=sys.stderr)
            
    return 0

def cmd_sweep(a) -> int:
    """Run every registered strategy on one symbol and print a ranked leaderboard."""
    if a.start and a.end:
        start, end = a.start, a.end
    else:
        end = datetime.now(tz=timezone.utc) - timedelta(minutes=2)
        start = end - timedelta(days=a.days)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if end <= start:
        print("invalid range", file=sys.stderr)
        return 2

    live = True if a.live is None else a.live
    base, _ = _resolve_urls(a, live=live)
    key, sec = _resolve_keys(a, live=live)
    client = DeltaClient(base, key, sec)
    print(
        f"[sweep] {a.symbol} @ {a.resolution}  {start.date()} → {end.date()}  "
        f"(SL {a.sl_pct}% / TP {a.tp_pct}% / trail {a.trail_pct}% / lev {a.leverage}x)"
    )

    bars = load_history(client, a.symbol, a.resolution, start, end)
    if not bars:
        msg = "no data returned; check symbol/timeframe/dates"
        if not live:
            msg += " — testnet has very limited history; retry without --testnet"
        print(msg, file=sys.stderr)
        return 2
    strategies = discover_strategies()
    print(f"[sweep] {len(bars)} bars loaded — running {len(strategies)} strategies")

    cfg = RunConfig(
        strategy="_sweep",
        symbol=a.symbol,
        resolution=a.resolution,
        capital=a.capital,
        params={},
        start=start,
        end=end,
        fee_bps=a.fee_bps,
        slippage_bps=a.slippage_bps,
        qty_pct=a.qty_pct,
        sl_pct=a.sl_pct,
        tp_pct=a.tp_pct,
        trail_pct=a.trail_pct,
        leverage=a.leverage,
    )

    from .reports.report import summarize

    rows = []
    for name in sorted(strategies.keys()):
        try:
            strat = load_strategy(name, {})
            pf = run_backtest(bars, strat, cfg)
            s = summarize(pf)
            rows.append({
                "strategy": name,
                "pnl": float(s["net_pnl"]),
                "return_pct": float(s["return_pct"]),
                "sharpe": float(s["sharpe"]),
                "winrate": float(s["win_rate_pct"]),
                "dd": float(s["max_drawdown_pct"]),
                "trades": int(s["trades"]),
                "pf": float(s["profit_factor"]),
            })
        except Exception as e:
            print(f"  ✗ {name:<24} ERROR: {e}", file=sys.stderr)

    rows = [r for r in rows if r["trades"] >= a.min_trades]
    if a.profitable_only:
        rows = [r for r in rows if r["pnl"] > 0]

    sort_key = {
        "pnl": "pnl", "return": "return_pct", "sharpe": "sharpe",
        "winrate": "winrate", "dd": "dd",
    }[a.sort]
    # max_drawdown is negative-good → sort ascending; everything else descending
    rows.sort(key=lambda r: r[sort_key], reverse=(a.sort != "dd"))
    if a.top and a.top > 0:
        rows = rows[: a.top]

    from .pnl_analytics import render_box_table, format_pnl, format_pct

    headers = ["Rank", "Strategy", "Net PnL ($)", "Return %", "Sharpe", "WinRate%", "Max DD%", "Trades", "PF"]
    table_rows = []
    for i, r in enumerate(rows, 1):
        table_rows.append([
            str(i),
            r["strategy"],
            format_pnl(r["pnl"]),
            format_pct(r["return_pct"]),
            f"{r['sharpe']:.2f}",
            f"{r['winrate']:.1f}%",
            f"{r['dd']:.2f}%",
            str(r["trades"]),
            f"{r['pf']:.2f}"
        ])

    title = f"LEADERBOARD — {a.symbol} @ {a.resolution} (sorted by {a.sort}, {len(rows)} strategies)"
    print("\n" + render_box_table(headers, table_rows, title=title))
    profitable = sum(1 for r in rows if r["pnl"] > 0)
    print(f"\nProfitable: {profitable} / {len(rows)}\n")

    if a.csv:
        import csv
        os.makedirs(os.path.dirname(a.csv) or ".", exist_ok=True)
        with open(a.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else
                               ["strategy", "pnl", "return_pct", "sharpe",
                                "winrate", "dd", "trades", "pf"])
            w.writeheader()
            w.writerows(rows)
        print(f"[sweep] wrote {a.csv}")
    return 0



def cmd_tasks(a) -> int:
    from .store.db import list_background_tasks, toggle_background_task, get_task_logs, connect
    from .pnl_analytics import render_box_table
    if a.tcmd in ("catalog", "scripts"):
        from .task_registry import get_catalog
        import json as _json
        cat = get_catalog()
        headers = ["Script Filename", "Task Name", "Category", "Default Interval", "Sample Properties / Inputs"]
        rows = []
        for item in cat:
            rows.append([
                item["script"],
                item["name"][:32],
                item["category"],
                f"{item['default_interval']}s",
                _json.dumps(item["params"])
            ])
        print("\n" + render_box_table(headers, rows, title="AVAILABLE TASK SCRIPTS & PROPERTY INPUTS CATALOG") + "\n")
        return 0
    if a.tcmd == "list":
        tasks = list_background_tasks()
        headers = ["ID", "Task Name", "Script", "Status", "Interval", "Last Run"]
        rows = []
        for t in tasks:
            rows.append([
                str(t["id"]),
                str(t["name"])[:24],
                str(t["script_name"])[:20],
                str(t["status"]),
                f"{t['interval_sec']}s",
                (t["last_run_at"] or "-").replace("T", " ")[:19]
            ])
        print("\n" + render_box_table(headers, rows, title="BACKGROUND TASKS & SCHEDULER") + "\n")
        return 0
    if a.tcmd == "pause-all" or (a.tcmd == "pause" and getattr(a, "all", False)):
        with connect() as conn:
            conn.execute("UPDATE background_tasks SET status='paused'")
        print("paused all background tasks")
        return 0
    if a.tcmd == "resume-all" or (a.tcmd == "resume" and getattr(a, "all", False)):
        with connect() as conn:
            conn.execute("UPDATE background_tasks SET status='running'")
        print("resumed all background tasks")
        return 0
    if a.tcmd == "pause":
        if a.id is None:
            print("Please specify --id <ID> or --all to pause tasks", file=sys.stderr)
            return 1
        toggle_background_task(a.id, "paused")
        print(f"paused background task #{a.id}")
        return 0
    if a.tcmd == "resume":
        if a.id is None:
            print("Please specify --id <ID> or --all to resume tasks", file=sys.stderr)
            return 1
        toggle_background_task(a.id, "running")
        print(f"resumed background task #{a.id}")
        return 0
    if a.tcmd == "logs":
        logs = get_task_logs(a.id, limit=a.limit)
        if not logs:
            print(f"(no logs for task #{a.id})")
            return 0
        for l in logs:
            print(f"[{l['ts'][:19]}] [{l['level']}] {l['message']}")
        return 0
    if a.tcmd == "rm":
        with connect() as conn:
            conn.execute("DELETE FROM background_tasks WHERE id=?", (a.id,))
        print(f"removed background task #{a.id}")
        return 0
    if a.tcmd == "add":
        import sqlite3
        try:
            with connect() as conn:
                conn.execute(
                    "INSERT INTO background_tasks(name, description, interval_sec, status, script_name, params_json) "
                    "VALUES (?, ?, ?, 'running', ?, ?)",
                    (a.name, a.desc or a.name, a.interval, a.script, a.params)
                )
            print(f"added background task '{a.name}'")
        except sqlite3.IntegrityError:
            print(f"\n[Error] A task with the name '{a.name}' already exists.")
            print("Please edit the existing task or use a different name.")
            return 1
        return 0
    if a.tcmd == "run-now":
        tasks = list_background_tasks()
        t = next((x for x in tasks if x["id"] == a.id), None)
        if not t:
            print(f"task #{a.id} not found", file=sys.stderr)
            return 1
        from importlib import import_module
        # strip .py extension — import_module needs the module name not the filename
        mod_name = t['script_name'].removesuffix('.py')
        try:
            mod = import_module(f"delta_bt.tasks.{mod_name}")
            fn = getattr(mod, "run", None) or getattr(mod, "main", None)
            if callable(fn):
                params = {}
                try:
                    import json as _pj
                    params = _pj.loads(t.get('params_json') or '{}')
                except Exception:
                    pass
                print(f"[tasks run-now] executing task #{a.id} ({mod_name})...")
                res = fn(**params)
                print(f"[tasks run-now] success: {res}")
            else:
                print(f"[tasks run-now] No run() or main() function found in delta_bt.tasks.{mod_name}", file=sys.stderr)
        except Exception as e:
            print(f"[tasks run-now] error executing task #{a.id}: {e}", file=sys.stderr)
            return 1
        return 0
    if a.tcmd == "edit":
        import json as _j
        with connect() as conn:
            if a.interval is not None:
                conn.execute("UPDATE background_tasks SET interval_sec=? WHERE id=?", (a.interval, a.id))
                print(f"  interval → {a.interval}s")
            if a.name is not None:
                conn.execute("UPDATE background_tasks SET name=? WHERE id=?", (a.name, a.id))
                print(f"  name     → {a.name}")
            if a.status is not None:
                conn.execute("UPDATE background_tasks SET status=? WHERE id=?", (a.status, a.id))
                print(f"  status   → {a.status}")
            if a.params is not None:
                # validate JSON before storing
                try:
                    _j.loads(a.params)
                except Exception as e:
                    print(f"[tasks edit] Invalid JSON params: {e}", file=sys.stderr)
                    return 1
                conn.execute("UPDATE background_tasks SET params_json=? WHERE id=?", (a.params, a.id))
                print(f"  params   → {a.params}")
        print(f"updated background task #{a.id}")
        return 0
    return 2


def cmd_pnl(a) -> int:
    from .pnl_analytics import get_portfolio_pnl, get_daily_pnl, generate_ascii_chart, render_box_table, format_pnl
    summary = get_portfolio_pnl()
    
    print("\n\033[1;36m┌─────────────────────────────────────────────────────────────┐\033[0m")
    print("\033[1;36m│\033[0m \033[1m📊 PORTFOLIO PnL & PERFORMANCE SUMMARY\033[0m                        \033[1;36m│\033[0m")
    print("\033[1;36m├─────────────────────────────────────────────────────────────┤\033[0m")
    print(f"\033[1;36m│\033[0m  Starting Capital : ${summary['starting_capital']:<38,.2f}\033[1;36m│\033[0m")
    print(f"\033[1;36m│\033[0m  Net Realized PnL : {format_pnl(summary['net_pnl']):<47}\033[1;36m│\033[0m")
    print(f"\033[1;36m│\033[0m  Total Trades     : {summary['total_trades']} ({summary['winning_trades']} W / {summary['losing_trades']} L)".ljust(62) + "\033[1;36m│\033[0m")
    print(f"\033[1;36m│\033[0m  Win Rate         : {summary['win_rate_pct']:.1f}%".ljust(62) + "\033[1;36m│\033[0m")
    print(f"\033[1;36m│\033[0m  Average Sharpe   : {summary['avg_sharpe']:.2f}".ljust(62) + "\033[1;36m│\033[0m")
    print(f"\033[1;36m│\033[0m  Average Max DD   : {summary['avg_max_dd_pct']:.2f}%".ljust(62) + "\033[1;36m│\033[0m")
    print(f"\033[1;36m│\033[0m  Best Trade PnL   : {format_pnl(summary['best_trade_pnl']):<47}\033[1;36m│\033[0m")
    print(f"\033[1;36m│\033[0m  Worst Trade PnL  : {format_pnl(summary['worst_trade_pnl']):<47}\033[1;36m│\033[0m")
    print(f"\033[1;36m│\033[0m  Total Fees Paid  : ${summary['total_fees']:<38,.2f}\033[1;36m│\033[0m")
    print(f"\033[1;36m│\033[0m  Active Bots      : {summary['active_bots']} / {summary['total_bots']}".ljust(62) + "\033[1;36m│\033[0m")
    print("\033[1;36m└─────────────────────────────────────────────────────────────┘\033[0m")
    
    if summary["equity_points"]:
        print("\n📈 EQUITY CURVE (ASCII):")
        print(generate_ascii_chart(summary["equity_points"]))

    daily = get_daily_pnl(limit=a.days)
    if daily:
        headers = ["Date", "Trades", "WinRate%", "Daily PnL ($)", "Max Win ($)", "Max Loss ($)"]
        rows = []
        for d in daily:
            rows.append([
                d["date"],
                str(d["trades"]),
                f"{d['win_rate_pct']:.1f}%",
                format_pnl(d["pnl"]),
                format_pnl(d["max_win"]),
                format_pnl(d["max_loss"])
            ])
        print("\n" + render_box_table(headers, rows, title=f"DAILY PnL BREAKDOWN (Last {len(daily)} active days)"))
    print()
    return 0


def cmd_pnl_strategy(_a) -> int:
    from .pnl_analytics import get_strategy_pnl_breakdown, render_box_table, format_pnl
    rows_data = get_strategy_pnl_breakdown()
    headers = ["Strategy", "Runs", "Trades", "WinRate%", "Net PnL ($)", "Sharpe", "Max DD%"]
    rows = []
    for r in rows_data:
        rows.append([
            r["strategy"][:24],
            str(r["runs"]),
            str(r["trades"]),
            f"{r['win_rate_pct']:.1f}%",
            format_pnl(r["pnl"]),
            f"{r['sharpe']:.2f}",
            f"{r['max_dd_pct']:.2f}%"
        ])
    print("\n" + render_box_table(headers, rows, title="STRATEGY PERFORMANCE LEADERBOARD") + "\n")
    return 0


def cmd_monitor(a) -> int:
    from .bot_monitor import run_live_terminal_monitor
    run_live_terminal_monitor(refresh_sec=a.interval)
    return 0


def cmd_bot_close_all(_a) -> int:
    from .bot_monitor import emergency_close_all
    print("🚨 EMERGENCY KILL-SWITCH INITIATED — Closing all open positions...")
    res = emergency_close_all()
    if res["closed"]:
        print(f"✅ Closed {len(res['closed'])} active position(s):")
        for item in res["closed"]:
            print(f"  • [{item['venue'].upper()}] {item['symbol']} — Qty: {item['qty']}")
    else:
        print("ℹ️ No active open positions found to close.")
    if res["errors"]:
        print(f"⚠️ Encountered {len(res['errors'])} error(s):")
        for err in res["errors"]:
            print(f"  • [{err.get('venue', 'ALL')}] {err.get('symbol', '')}: {err['error']}")
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return {
        "backtest": cmd_backtest,
        "paper": cmd_paper,
        "live": cmd_live,
        "list-strategies": cmd_list,
        "runs": cmd_runs,
        "run-show": cmd_run_show,
        "trades": cmd_trades,
        "compare": cmd_compare,
        "plot": cmd_plot,
        "plot-diag": cmd_plot_diag,
        "serve": cmd_serve,
        "scan": cmd_scan,
        "rank-universe": cmd_rank_universe,
        "balance": cmd_balance,
        "folio": cmd_folio,
        "trade": cmd_trade,
        "order": cmd_order,
        "watch": cmd_watch,
        "deployments": cmd_deployments,
        "activity": cmd_activity,
        "bots": cmd_bots,
        "bot-show": cmd_bot_show,
        "bot-events": cmd_bot_events,
        "db-info": cmd_db_info,
        "db-path": cmd_db_path,
        "db-vacuum": cmd_db_vacuum,
        "db-clear": cmd_db_clear,
        "factory-reset": cmd_factory_reset,
        "sweep": cmd_sweep,
        "auto-deploy": cmd_auto_deploy,
        "tasks": cmd_tasks,
        "pnl": cmd_pnl,
        "pnl-strategy": cmd_pnl_strategy,
        "monitor": cmd_monitor,
        "dashboard": cmd_monitor,
        "bot-close-all": cmd_bot_close_all,
    }[args.cmd](args)



if __name__ == "__main__":
    raise SystemExit(main())

