from __future__ import annotations

import unittest

from server_a.hermes.clients.ai_client import AIClientConfig, HermesAIClient
from server_a.hermes.gate import deployment_gate
from server_a.hermes.orchestrator import apply_ai_suggestion


class FakeAIClient(HermesAIClient):
    def __init__(self, suggestion):
        super().__init__(AIClientConfig("deepseek", "key", "http://example.invalid", "model"))
        self.suggestion = suggestion

    async def suggest(self, payload):
        return self.suggestion


class HermesAITests(unittest.IsolatedAsyncioTestCase):
    async def test_no_provider_keeps_rule_based_decision(self):
        report = {
            "performance": {},
            "decision": {
                "action": "KEEP",
                "reason": "rule",
                "strategy_config": {"active_strategy_ids": ["MACD_RSI_MOMENTUM"], "mode": "auto"},
                "risk_config": {"risk_per_trade": 0.01, "max_leverage": 3, "max_open_positions": 3},
            },
            "deployable": True,
            "gate_reason": "ok",
        }
        result = await apply_ai_suggestion(report, HermesAIClient(AIClientConfig("", "", "", "")))
        self.assertFalse(result["ai"]["used"])
        self.assertEqual(result["decision"]["action"], "KEEP")

    async def test_ai_risk_increase_is_clamped(self):
        report = {
            "performance": {},
            "decision": {
                "action": "KEEP",
                "reason": "rule",
                "strategy_config": {"active_strategy_ids": ["MACD_RSI_MOMENTUM"], "mode": "auto"},
                "risk_config": {"risk_per_trade": 0.01, "max_leverage": 3, "max_open_positions": 3},
            },
            "deployable": True,
            "gate_reason": "ok",
        }
        result = await apply_ai_suggestion(report, FakeAIClient({
            "action": "REDUCE_RISK",
            "reason": "test",
            "risk_config": {"risk_per_trade": 0.5, "max_leverage": 20, "max_open_positions": 10},
        }))
        risk = result["decision"]["risk_config"]
        self.assertEqual(risk["risk_per_trade"], 0.01)
        self.assertEqual(risk["max_leverage"], 3)
        self.assertEqual(risk["max_open_positions"], 3)
        allowed, reason = deployment_gate(result["decision"])
        self.assertTrue(allowed, reason)


if __name__ == "__main__":
    unittest.main()
