from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def decide_strategy_action(performance: dict[str, Any], current_strategy_ids: list[str] | None = None) -> dict[str, Any]:
    current = current_strategy_ids or ["MACD_RSI_MOMENTUM"]
    count = int(performance.get("trade_count", 0))
    net = float(performance.get("net_pnl", 0.0))
    win_rate = float(performance.get("win_rate", 0.0))
    profit_factor = float(performance.get("profit_factor", 0.0))
    max_drawdown = float(performance.get("max_drawdown", 0.0))
    consecutive_losses = _consecutive_losses(performance.get("rows", []))

    action = "KEEP"
    reason = "Recent performance passes keep criteria"
    active = list(current)
    disabled: list[str] = []
    risk_multiplier = 1.0
    min_score = 65

    if count >= 30 and (net < 0 or profit_factor < 1.0 or max_drawdown > 0.10):
        action = "DISABLE_STRATEGY"
        reason = "Recent 30+ trades failed disable criteria"
        disabled = active[:]
        active = []
    elif consecutive_losses >= 3:
        action = "REDUCE_RISK"
        reason = "Consecutive losses >= 3"
        risk_multiplier = 0.5
        min_score = 70
    elif count >= 50 and net > 0 and win_rate >= 0.45 and profit_factor >= 1.2 and max_drawdown <= 0.08:
        action = "KEEP"
    elif win_rate >= 0.45 and profit_factor < 1.2:
        action = "TUNE_PARAMETERS"
        reason = "Win rate acceptable but profit factor is weak"
        min_score = 70
    elif count < 30:
        action = "TUNE_PARAMETERS"
        reason = "Trade sample is too small; keep strategy but tighten entries"
        min_score = 70
    elif max_drawdown > 0.08:
        action = "REDUCE_RISK"
        reason = "Drawdown above 8%"
        risk_multiplier = 0.5
        min_score = 70

    now = datetime.now(timezone.utc).isoformat()
    return {
        "action": action,
        "reason": reason,
        "strategy_config": {
            "active_strategy_ids": active or current,
            "disabled_strategy_ids": disabled,
            "mode": "auto" if active else "paused",
            "min_score": min_score,
            "updated_at": now,
            "reason": reason,
        },
        "risk_config": {
            "max_open_positions": 3,
            "risk_per_trade": round(0.01 * risk_multiplier, 4),
            "max_leverage": 3,
            "daily_loss_limit": 0.03,
            "weekly_drawdown_limit": 0.08,
            "updated_at": now,
            "reason": reason,
        },
    }


def _consecutive_losses(rows: list[dict]) -> int:
    count = 0
    for row in reversed(rows):
        try:
            pnl = float(row.get("pnl") or 0.0)
        except (TypeError, ValueError):
            pnl = 0.0
        if pnl < 0:
            count += 1
        else:
            break
    return count
