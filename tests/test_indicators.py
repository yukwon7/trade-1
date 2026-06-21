import unittest

from indicators import atr, ema, rsi, volume_ratio
from models import Candle


class IndicatorTests(unittest.TestCase):
    def test_ema_tracks_constant_series(self):
        self.assertEqual(ema([10.0] * 20, 5), [10.0] * 20)

    def test_rsi_extremes(self):
        values = list(range(1, 40))
        self.assertAlmostEqual(rsi(values)[-1], 100.0)
        self.assertLess(rsi(list(reversed(values)))[-1], 1.0)

    def test_atr_and_volume_ratio(self):
        candles = [Candle(i, 10, 11, 9, 10, 100) for i in range(30)]
        self.assertAlmostEqual(atr(candles)[-1], 2.0)
        self.assertAlmostEqual(volume_ratio([100] * 30)[-1], 1.0)


if __name__ == "__main__":
    unittest.main()
