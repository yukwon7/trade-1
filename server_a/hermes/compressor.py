from __future__ import annotations


def compact_performance(performance: dict) -> dict:
    return {
        "trade_count": performance.get("trade_count", 0),
        "net_pnl": round(float(performance.get("net_pnl", 0.0)), 4),
        "win_rate": round(float(performance.get("win_rate", 0.0)), 4),
        "profit_factor": round(float(performance.get("profit_factor", 0.0)), 4),
        "max_drawdown": round(float(performance.get("max_drawdown", 0.0)), 4),
        "expectancy": round(float(performance.get("expectancy", 0.0)), 4),
        "long_short": performance.get("long_short", {}),
        "by_strategy": {
            key: {
                "trade_count": value.get("trade_count", 0),
                "net_pnl": round(float(value.get("net_pnl", 0.0)), 4),
                "profit_factor": round(float(value.get("profit_factor", 0.0)), 4),
            }
            for key, value in (performance.get("by_strategy") or {}).items()
        },
    }
