# delta-cli Background Task Blacklist & Risk Config
# Audited on: 2026-08-11
#
# ─── BLACKLISTED TASKS (permanently paused — do NOT re-enable) ─────────
#
# id=93 | Volatility Grid Farmer        | volatility_grid_farmer
#   REASON: venue=live with auto-deploy=true — DANGEROUS, deploys live bots
#           without coin-overlap checks. Can fire duplicate orders on BTCUSD/ETHUSD.
#
# id=102 | Options Delta Hedger          | options_delta_hedger
#   REASON: Delta Exchange India does not offer options contracts — unnecessary.
#
# id=103 | "Smc Hunter" (dup of id=90)   | smc_hunter.py
#   REASON: Exact duplicate of id=90 (same script, slower interval).
#           Wastes API quota and spawns duplicate scan processes.
#
# id=104 | "11" (generic name, dup)      | smc_hunter.py
#   REASON: Generic unnamed task — duplicate of id=90 and id=103.
#           Cannot be meaningfully managed with no descriptive name.
#
# id=105 | "KS" (generic name)           | keltner_scanner.py
#   REASON: Generic unnamed task — redundant with other volatility scanners
#           (id=94 Volume Anomaly Sniper covers volume-based setups).
#
# id=107 | anti_correlation_deployer_894 | anti_correlation_deployer
#   REASON: Only useful when scanner tasks have auto_deploy=true (which is disabled).
#           Standalone auto-deploy without coin-overlap guard is dangerous.
#
# ─── RISK CONFIG ADJUSTMENTS (for $49 account) ─────────────────────────
#
# id=83 | Capital Allocator
#   CHANGE: auto_apply=False (was default True)
#   REASON: Auto-rebalancing is too aggressive for $49 account. Scale-up/down
#           logic makes minimal impact at this capital level. Use for reports only.
#
# id=86 | Global Exposure Manager
#   CHANGE: max_exposure_usd=25.0 (was default 10000.0)
#   REASON: Default $10,000 exposure cap is 200x account size. Would allow
#           catastrophic over-leveraging. $25 = ~50% of $49 account.
#
# id=100 | ATR Position Sizer
#   CHANGE: target_risk_usd=2.0 (was default 100.0)
#   REASON: Default $100 risk/lot means a 1.5% SL = $1.50 risk per lot.
#           With $49 account, this allows ~33 lots = extreme over-leveraging.
#           $2 risk/lot = 0.03 lot per $49 → appropriate sizing.
#
# ─── HUNTER TASKS (alert-only mode) ────────────────────────────────────
#
# All hunter tasks (id 80,82,88,89,90,91,94,97,98,93) have auto_deploy=False
# and dry_run=True set in params_json. They scan and report — they do NOT deploy.

BLACKLIST_TASK_IDS = [93, 102, 103, 104, 105, 107]
RISK_CONFIG_ADJUSTMENTS = {
    83: {"auto_apply": False},
    86: {"max_exposure_usd": 25.0},
    100: {"target_risk_usd": 2.0},
}
HUNTER_TASK_IDS = [80, 82, 88, 89, 90, 91, 94, 97, 98, 93]
