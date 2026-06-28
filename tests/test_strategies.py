import unittest
from pathlib import Path

from models import Candle
from strategies import STRATEGIES, STRATEGY_ROTATION_IDS
from strategies.market_router import ChartAdaptiveRouterStrategy, build_catalog_strategies
from tests.helpers import candles


class StrategyTests(unittest.TestCase):
    def test_all_ten_strategies_registered_with_requested_leverage(self):
        catalog = [key for key in STRATEGIES if key.startswith("S") and key[1:].isdigit() and 20 <= int(key[1:]) <= 55]
        self.assertEqual(list(STRATEGY_ROTATION_IDS), ["S99"])
        self.assertEqual(len(catalog), 36)
        self.assertTrue(all(STRATEGIES[key].leverage <= 3 for key in catalog))
        self.assertEqual(STRATEGIES["S99"].leverage, 3)

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
