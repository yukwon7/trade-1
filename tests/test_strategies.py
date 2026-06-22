import unittest

from models import Candle
from strategies import STRATEGIES
from tests.helpers import candles


class StrategyTests(unittest.TestCase):
    def test_all_ten_strategies_registered_with_requested_leverage(self):
        self.assertEqual(list(STRATEGIES), [f"S{index:02d}" for index in range(1, 11)])
        self.assertEqual([item.leverage for item in STRATEGIES.values()], [5, 7, 5, 10, 5, 3, 7, 5, 4, 6])

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


if __name__ == "__main__":
    unittest.main()
