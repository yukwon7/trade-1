from __future__ import annotations

from copy import deepcopy
from typing import Any

from server_a.hermes.clients.ai_client import HermesAIClient


ALLOWED_ACTIONS = {"KEEP", "TUNE_PARAMETERS", "DISABLE_STRATEGY", "REPLACE_STRATEGY", "REDUCE_RISK"}
ACTION_SEVERITY = {
    "KEEP": 0,
    "TUNE_PARAMETERS": 1,
    "REDUCE_RISK": 2,
    "DISABLE_STRATEGY": 3,
    "REPLACE_STRATEGY": 3,
}


async def apply_ai_suggestion(base_report: dict[str, Any], ai_client: HermesAIClient | None = None) -> dict[str, Any]:
    client = ai_client or HermesAIClient.from_env()
    payload = {
        "performance": base_report.get("performance", {}),
        "decision": base_report.get("decision", {}),
        "deployable": base_report.get("deployable"),
        "gate_reason": base_report.get("gate_reason"),
    }
    suggestion = await client.suggest(payload)
    if not suggestion:
        base_report["ai"] = {
            "enabled": client.config.enabled,
            "provider": client.config.provider or "none",
            "used": False,
            "reason": "no AI provider configured or no valid suggestion",
        }
        return base_report

    merged = deepcopy(base_report)
    decision = deepcopy(merged.get("decision") or {})
    base_action = str(decision.get("action") or "").upper()
    action = str(suggestion.get("action") or base_action).upper()
    if action in ALLOWED_ACTIONS and ACTION_SEVERITY.get(action, 0) >= ACTION_SEVERITY.get(base_action, 0):
        decision["action"] = action
    if suggestion.get("reason"):
        decision["reason"] = str(suggestion["reason"])[:500]
    if isinstance(suggestion.get("strategy_config"), dict):
        decision["strategy_config"] = _safe_strategy_config(decision.get("strategy_config") or {}, suggestion["strategy_config"])
    if isinstance(suggestion.get("risk_config"), dict):
        decision["risk_config"] = _safe_risk_config(decision.get("risk_config") or {}, suggestion["risk_config"])
    merged["decision"] = decision
    merged["ai"] = {
        "enabled": client.config.enabled,
        "provider": client.config.provider,
        "model": client.config.model,
        "used": True,
        "raw_action": suggestion.get("action"),
    }
    return merged


def _safe_strategy_config(base: dict, suggestion: dict) -> dict:
    output = deepcopy(base)
    if isinstance(suggestion.get("active_strategy_ids"), list):
        output["active_strategy_ids"] = [str(item).upper() for item in suggestion["active_strategy_ids"][:3]]
    if isinstance(suggestion.get("disabled_strategy_ids"), list):
        output["disabled_strategy_ids"] = [str(item).upper() for item in suggestion["disabled_strategy_ids"][:20]]
    if str(suggestion.get("mode", "")).lower() in {"auto", "manual", "paused"}:
        output["mode"] = str(suggestion["mode"]).lower()
    if "min_score" in suggestion:
        output["min_score"] = min(100, max(0, float(suggestion["min_score"])))
    if suggestion.get("reason"):
        output["reason"] = str(suggestion["reason"])[:500]
    return output


def _safe_risk_config(base: dict, suggestion: dict) -> dict:
    output = deepcopy(base)
    if "max_open_positions" in suggestion:
        output["max_open_positions"] = min(3, max(1, int(suggestion["max_open_positions"])))
    if "risk_per_trade" in suggestion:
        output["risk_per_trade"] = min(0.01, max(0.001, float(suggestion["risk_per_trade"])))
    if "max_leverage" in suggestion:
        output["max_leverage"] = min(3, max(1, int(suggestion["max_leverage"])))
    if "daily_loss_limit" in suggestion:
        output["daily_loss_limit"] = min(0.05, max(0.01, float(suggestion["daily_loss_limit"])))
    if "weekly_drawdown_limit" in suggestion:
        output["weekly_drawdown_limit"] = min(0.10, max(0.02, float(suggestion["weekly_drawdown_limit"])))
    return output
