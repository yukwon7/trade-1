from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from execution.config_reloader import ConfigReloader
from execution.risk_engine import ExecutionRiskEngine
from models import StrategySignal


class ExecutionConfigTests(unittest.TestCase):
    def test_reloader_accepts_valid_config_and_rejects_invalid_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "strategy_config.json").write_text(json.dumps({
                "active_strategy_ids": ["MACD_RSI_MOMENTUM"],
                "disabled_strategy_ids": [],
                "mode": "auto",
                "min_score": 65,
            }), encoding="utf-8")
            (path / "risk_config.json").write_text(json.dumps({
                "max_open_positions": 3,
                "risk_per_trade": 0.01,
                "max_leverage": 3,
                "daily_loss_limit": 0.03,
                "weekly_drawdown_limit": 0.08,
            }), encoding="utf-8")
            (path / "selected_symbols.json").write_text(json.dumps({"symbols": ["BTCUSDT", "ETHUSDT"]}), encoding="utf-8")

            reloader = ConfigReloader(path)
            runtime = reloader.reload()
            self.assertEqual(runtime.strategy.active_strategy_ids, ("MACD_RSI_MOMENTUM",))
            self.assertEqual(runtime.risk.max_open_positions, 3)
            self.assertEqual(runtime.symbols.symbols, ("BTCUSDT", "ETHUSDT"))

            (path / "risk_config.json").write_text(json.dumps({"max_leverage": 10}), encoding="utf-8")
            runtime = reloader.reload()
            self.assertEqual(runtime.risk.max_leverage, 3)
            self.assertIn("risk_config.json", reloader.last_errors)

    def test_risk_engine_supports_alias_and_clamps_leverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "strategy_config.json").write_text(json.dumps({"active_strategy_ids": ["MACD_RSI_MOMENTUM"]}), encoding="utf-8")
            (path / "risk_config.json").write_text(json.dumps({"max_leverage": 3}), encoding="utf-8")
            runtime = ConfigReloader(path).reload()
            signal = StrategySignal(
                strategy_id="S25",
                strategy_name="MACD_RSI_MOMENTUM",
                symbol="BTCUSDT",
                direction="LONG",
                entry_price=100.0,
                leverage=10,
                stop_loss_pct=0.01,
                take_profit_pct=0.02,
                reason="test",
                metadata={"score": 70},
            )
            filtered = ExecutionRiskEngine(runtime).filter_signal(signal)
            self.assertIsNotNone(filtered)
            self.assertEqual(filtered.leverage, 3)


if __name__ == "__main__":
    unittest.main()
