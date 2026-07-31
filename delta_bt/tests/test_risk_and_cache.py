import unittest
from delta_bt.risk_core import RiskParams, RiskState, effective_sl_px, _exit_reason
from delta_bt.scheduler import _get_risk_mode_prices
from delta_bt.cache import get_cache


class TestRiskAndCache(unittest.TestCase):

    def test_risk_core_modes(self):
        # Percentage mode
        p_pct = RiskParams(side="buy", entry=100.0, sl_pct=2.0, tp_pct=5.0, trail_pct=1.0, sl_type="pct", tp_type="pct", trail_type="pct")
        s_pct = RiskState(peak=110.0, trough=100.0, trail_armed=True)
        self.assertEqual(effective_sl_px(p_pct, s_pct), 108.9)  # 110 * (1 - 0.01)

        # ATR mode
        p_atr = RiskParams(side="buy", entry=100.0, sl_pct=2.0, tp_pct=3.0, trail_pct=1.5, sl_type="atr", tp_type="atr", trail_type="atr", atr_val=2.5)
        s_atr = RiskState(peak=105.0, trough=100.0, trail_armed=True)
        # sl = 100 - (2 * 2.5) = 95. trail = 105 - (1.5 * 2.5) = 101.25 -> max = 101.25
        self.assertEqual(effective_sl_px(p_atr, s_atr), 101.25)

        # Point mode
        p_pt = RiskParams(side="sell", entry=100.0, sl_pct=10.0, tp_pct=20.0, trail_pct=5.0, sl_type="point", tp_type="point", trail_type="point")
        s_pt = RiskState(peak=100.0, trough=90.0, trail_armed=True)
        # sl = 100 + 10 = 110. trail = 90 + 5 = 95 -> min = 95
        self.assertEqual(effective_sl_px(p_pt, s_pt), 95.0)

    def test_scheduler_risk_mode_prices(self):
        row_pct = {"open_side": "buy", "sl_pct": 2.0, "tp_pct": 4.0, "trail_pct": 1.0, "leverage": 1, "params_json": '{"sl_type": "pct", "tp_type": "pct"}'}
        sl, tp, trail = _get_risk_mode_prices(row_pct, 100.0, 105.0)
        self.assertAlmostEqual(sl, 98.0)
        self.assertAlmostEqual(tp, 104.0)
        self.assertAlmostEqual(trail, 103.95)

        row_pt = {"open_side": "sell", "sl_pct": 15.0, "tp_pct": 30.0, "trail_pct": 10.0, "leverage": 1, "params_json": '{"sl_type": "point", "tp_type": "point", "trail_type": "point"}'}
        sl2, tp2, trail2 = _get_risk_mode_prices(row_pt, 1000.0, 900.0)
        self.assertEqual(sl2, 1015.0)
        self.assertEqual(tp2, 970.0)
        self.assertEqual(trail2, 910.0)

    def test_cache_manager(self):
        cache = get_cache()
        cache.set("test_key", {"status": "ok"}, ttl=10)
        self.assertEqual(cache.get("test_key"), {"status": "ok"})
        status = cache.status()
        self.assertIn("up", status)
        self.assertIn("backend", status)


if __name__ == "__main__":
    unittest.main()
