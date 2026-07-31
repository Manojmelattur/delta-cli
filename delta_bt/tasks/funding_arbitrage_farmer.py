from datetime import datetime, timezone

from delta_bt.data.delta_client import DeltaClient


def run(**kwargs):
    """
    Delta-Neutral Funding Rate Farmer Task.
    Scans active perpetual ticker contracts for high positive funding rates
    and highlights delta-neutral yield farming opportunities.

    Strategy:
      Positive APY → Short Perp + Long Spot (collect funding)
      Negative APY → Long Perp + Short Spot (collect negative funding)
    """
    min_apy           = float(kwargs.get("min_apy",           20.0))
    # Fix 5: configurable intervals per day (default 3 = 8h interval)
    intervals_per_day = float(kwargs.get("intervals_per_day", 3.0))
    top_n             = int(kwargs.get("top_n",               10))

    # Fix 1+3: use DeltaClient with correct base URL
    client = DeltaClient(base_url="https://api.india.delta.exchange")

    try:
        # Fix 2: use built-in contract_types filter instead of manual loop filter
        tickers = client.tickers(contract_types="perpetual_futures")
    except Exception as e:
        return f"Funding Arbitrage Farmer: Failed to fetch tickers — {e}"

    if not tickers:
        return "Funding Arbitrage Farmer: No perpetual futures tickers returned."

    opps = []

    for t in tickers:
        symbol       = t.get("symbol", "")
        funding_rate = float(t.get("funding_rate", 0) or 0)
        mark_price   = float(t.get("mark_price",   0) or 0)

        if not symbol:
            continue

        # Fix 5: use configurable intervals_per_day
        # funding_rate is decimal per interval (e.g. 0.0001 = 0.01% per 8h)
        annualized_apy     = funding_rate * intervals_per_day * 365 * 100.0
        funding_rate_pct   = funding_rate * 100.0

        if abs(annualized_apy) >= min_apy:
            direction = (
                "Farm Yield (Short Perp + Long Spot)"
                if annualized_apy > 0
                else "Reverse Farm (Long Perp + Short Spot)"
            )
            opps.append({
                "symbol":           symbol,
                # Fix 4: renamed to funding_rate_pct to avoid implying fixed 8h interval
                "funding_rate_pct": funding_rate_pct,
                "apy":              annualized_apy,
                "mark_price":       mark_price,
                "direction":        direction,
            })

    if not opps:
        return (
            f"Funding Arbitrage Farmer: No perpetual pairs currently "
            f"exceed {min_apy}% APY threshold."
        )

    opps.sort(key=lambda x: abs(x["apy"]), reverse=True)

    lines = [
        f"Top Delta-Neutral Funding Rate Opportunities (Min APY {min_apy}%, "
        f"intervals/day={intervals_per_day:.0f}):"
    ]
    for o in opps[:top_n]:
        lines.append(
            f"  {o['symbol']} | "
            f"Rate: {o['funding_rate_pct']:.4f}% | "
            f"APY: {o['apy']:.2f}% | "
            f"Mark: ${o['mark_price']:.4f} | "
            f"{o['direction']}"
        )

    return "\n".join(lines)
