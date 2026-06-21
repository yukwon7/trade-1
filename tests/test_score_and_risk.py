import unittest
from datetime import datetime, timezone

from models import IndicatorSnapshot, PositionState
from risk import CircuitBreaker, PyramidManager, StopManager, calculate_position_size, leverage_for_score
from strategy import ScoreEngine


def snapshot(timeframe="5m", ema20=110, ema50=100, rsi=65, adx=28, volume_ratio=2.1):
    return IndicatorSnapshot("BTCUSDT", timeframe, 110, ema20, ema50, rsi, adx, 2, 2, volume_ratio, 95, 108, 107, 111, 106)


class ScoreAndRiskTests(unittest.TestCase):
    def test_full_long_score(self):
        score, parts = ScoreEngine.calculate("LONG", snapshot("1h"), snapshot("15m"), snapshot(), True, True)
        self.assertEqual(score, 95)
        self.assertEqual(parts["trend"], 30)

    def test_adx_below_twenty_invalidates(self):
        score, _ = ScoreEngine.calculate("LONG", snapshot("1h"), snapshot("15m"), snapshot(adx=19), True, True)
        self.assertEqual(score, 0)

    def test_leverage_thresholds(self):
        self.assertEqual(leverage_for_score(85, 5), 5)
        self.assertEqual(leverage_for_score(75, 5), 3)
        self.assertEqual(leverage_for_score(65, 5), 2)
        self.assertEqual(leverage_for_score(64, 5), 0)

    def test_position_size_caps_margin(self):
        quantity = calculate_position_size(1000, 0.01, 100, 98, 2, 100)
        self.assertEqual(quantity, 2.0)

    def test_stop_to_break_even(self):
        position = PositionState(
            id=None, symbol="BTCUSDT", direction="LONG", entry_price=100,
            current_price=100, size=1, leverage=2, initial_atr=1,
            sl_price=98.5, tp_price=103, initial_size=1,
            remaining_size=1, score=80,
        )
        self.assertIsNone(StopManager.update(position, 101.6, 99, 101))
        self.assertEqual(position.sl_price, 100)
        event = StopManager.update(position, 101, 99.9, 100)
        self.assertEqual(event.reason, "BREAK_EVEN")

    def test_pyramiding_only_in_profit(self):
        position = PositionState(
            id=None, symbol="BTCUSDT", direction="LONG", entry_price=100,
            current_price=100, size=4, leverage=2, initial_atr=1,
            sl_price=98.5, tp_price=103, initial_size=4,
            remaining_size=4, score=80,
        )
        self.assertEqual(PyramidManager.next_add_size(position, 100.2, True), 0)
        self.assertGreater(PyramidManager.next_add_size(position, 100.6, True), 0)


class CircuitBreakerTests(unittest.IsolatedAsyncioTestCase):
    async def test_seven_losses_requires_ten_samples(self):
        class Store:
            async def risk_state(self, symbol):
                return {
                    "daily_pnl": 0, "consecutive_losses": 0, "last_loss_at": None,
                    "symbol_last_stop_at": None, "symbol_last_10_count": 7,
                    "symbol_last_10_losses": 7,
                    "symbol_last_loss_at": datetime.now(timezone.utc).isoformat(),
                }
        allowed, _, _ = await CircuitBreaker(Store()).allow_entry("BTCUSDT", 1000)
        self.assertTrue(allowed)


if __name__ == "__main__":
    unittest.main()
