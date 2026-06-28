from __future__ import annotations


def deployment_gate(decision: dict) -> tuple[bool, str]:
    action = decision.get("action")
    strategy = decision.get("strategy_config") or {}
    risk = decision.get("risk_config") or {}
    if action == "REPLACE_STRATEGY":
        return False, "replacement requires explicit backtest/stress proof"
    if float(risk.get("risk_per_trade", 0.0)) > 0.01:
        return False, "risk_per_trade cannot increase automatically"
    if int(risk.get("max_leverage", 0)) > 3:
        return False, "max_leverage cannot exceed 3"
    if len(strategy.get("active_strategy_ids") or []) > 3:
        return False, "Server B supports at most 3 active strategies"
    return True, "ok"
