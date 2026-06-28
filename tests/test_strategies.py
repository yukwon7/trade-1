import unittest
from pathlib import Path

from models import Candle
from strategies import STRATEGIES, STRATEGY_ROTATION_IDS
from strategies.s99_adaptive_ensemble import AdaptiveEnsembleStrategy
from tests.helpers import candles


class StrategyTests(unittest.TestCase):
    def test_all_ten_strategies_registered_with_requested_leverage(self):
        self.assertEqual(list(STRATEGY_ROTATION_IDS), [f"S{index:02d}" for index in range(1, 11)])
        self.assertEqual([STRATEGIES[key].leverage for key in STRATEGY_ROTATION_IDS], [5, 7, 5, 10, 5, 3, 7, 5, 4, 6])
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

    def test_adaptive_ensemble_requires_confirming_votes(self):
        data = candles()
        data[-1] = Candle(data[-1].open_time, 100, 111, 99.5, 110, 1000, 100000)
        strategy = AdaptiveEnsembleStrategy(Path("__missing_test_config__.json"))
        signal = strategy.evaluate("BTCUSDT", data, data)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction, "LONG")
        self.assertIn("S02", signal.metadata["votes"])
        self.assertIn("S07", signal.metadata["votes"])


if __name__ == "__main__":
    unittest.main()
