import unittest
from pathlib import Path

from models import Candle
from strategies import STRATEGIES, STRATEGY_ROTATION_IDS
from strategies.market_router import ChartAdaptiveRouterStrategy, build_catalog_strategies
from tests.helpers import candles


class StrategyTests(unittest.TestCase):
    def test_all_ten_strategies_registered_with_requested_leverage(self):
        legacy = [f"S{index:02d}" for index in range(1, 11)]
        catalog = [key for key in STRATEGIES if key.startswith("S") and key[1:].isdigit() and 20 <= int(key[1:]) <= 55]
        self.assertEqual(list(STRATEGY_ROTATION_IDS), ["S99"])
        self.assertEqual([STRATEGIES[key].leverage for key in legacy], [5, 7, 5, 10, 5, 3, 7, 5, 4, 6])
        self.assertEqual(len(catalog), 36)
        self.assertTrue(all(STRATEGIES[key].leverage <= 3 for key in catalog))
        self.assertEqual(STRATEGIES["S99"].leverage, 3)

    def test_ema_cross_fast_long_signal(self):
        data = candles()
        data[-1] = Candle(data[-1].open_time, 100, 111, 99.5, 110, 1000, 100000)
        signal = STRATEGIES["S02"].evaluate("BTCUSDT", data, data)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction, "LONG")

    def test_order_imbalance_uses_live_depth(self):
        data = candles()
        data[-2] = Candle(data[-2].open_time, 100, 100, 100, 100, 100)
        context = {
            "mark_price": 100.2,
            "bids": [["100", "30"]] * 20,
            "asks": [["101", "10"]] * 20,
        }
        signal = STRATEGIES["S04"].evaluate("BTCUSDT", data, data, context)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.leverage, 10)

    def test_breakout_volume_signal(self):
        data = candles()
        data[-1] = Candle(data[-1].open_time, 100, 102, 99, 101, 300, 30000)
        signal = STRATEGIES["S07"].evaluate("BTCUSDT", data, data)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction, "LONG")

    def test_chart_router_selects_catalog_strategy(self):
        data = candles()
        data[-1] = Candle(data[-1].open_time, 100, 111, 99.5, 110, 1000, 100000)
        router = ChartAdaptiveRouterStrategy(build_catalog_strategies(), Path("__missing_router_config__.json"))
        signal = router.evaluate("BTCUSDT", data, data)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction, "LONG")
        self.assertNotEqual(signal.strategy_id, "S99")
        self.assertTrue(20 <= int(signal.strategy_id[1:]) <= 55)
        self.assertIn("router_regime", signal.metadata)


if __name__ == "__main__":
    unittest.main()
