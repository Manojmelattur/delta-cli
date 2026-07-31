# Risk Management Tasks — User Guide

## Overview

Fourteen automated risk management tasks protect your deployments at
every level — from individual position sizing to portfolio-wide exposure
and execution quality monitoring.

---

## Quick Reference

| Task | File | Interval | Opt-in | Key Params |
|------|------|----------|--------|------------|
| ATR Position Sizer      | atr_position_sizer.py    | 4h   | params_json | target_risk_usd |
| ATR Risk Manager        | atr_risk_manager.py      | 4h   | params_json | atr_sl_multiplier |
| Max Drawdown Guard      | max_drawdown_guard.py    | 15m  | all (opt-out) | dd_threshold_pct |
| Daily Loss Limit        | daily_loss_limit.py      | 15m  | all (opt-out) | daily_loss_limit_usd |
| Correlation Limiter     | correlation_limiter.py   | 30m  | all (opt-out) | correlation_threshold |
| Position Age Timeout    | position_age_timeout.py  | 30m  | all (opt-out) | max_position_age_hours |
| Volatility Regime Sizer | volatility_regime_sizer.py | 4h | params_json | vol_target_risk_usd |
| Kelly Sizer             | kelly_sizer.py           | 24h  | params_json | kelly_fraction |
| Equity Curve Filter     | equity_curve_filter.py   | 4h   | params_json | eq_ma_period |
| Max Open Positions      | max_open_positions.py    | 15m  | all          | max_positions |
| Sector Exposure Cap     | sector_exposure_cap.py   | 30m  | all          | sector_caps |
| Margin Utilisation Guard| margin_utilisation_guard.py | 15m | all        | margin_threshold_pct |
| Slippage Monitor        | slippage_monitor.py      | 24h  | all          | slippage_threshold_bps |
| Fill Rate Monitor       | fill_rate_monitor.py     | 4h   | all          | fill_rate_threshold |
| Funding Rate Guard      | funding_rate_guard.py    | 1h   | all          | funding_threshold_pct |
| Liquidity Guard         | liquidity_guard.py       | 4h   | all          | min_volume_usd |

---

## Opt-in vs Opt-out

### Opt-in tasks
These tasks only act on deployments that explicitly enable them via
`params_json`. Set the flag in your deployment configuration:

```json
{
  "use_atr_risk":      true,
  "use_vol_sizer":     true,
  "use_kelly_sizer":   true,
  "use_equity_filter": true
}
