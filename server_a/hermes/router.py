from __future__ import annotations

from server_a.analytics import analyze_performance, decide_strategy_action
from server_a.hermes.compressor import compact_performance
from server_a.hermes.gate import deployment_gate


def build_decision(settings, current_strategy_ids: list[str] | None = None) -> dict:
    performance = analyze_performance(settings.database_path, settings.initial_balance)
    decision = decide_strategy_action(performance, current_strategy_ids)
    allowed, gate_reason = deployment_gate(decision)
    return {
        "performance": compact_performance(performance),
        "decision": decision,
        "deployable": allowed,
        "gate_reason": gate_reason,
    }
