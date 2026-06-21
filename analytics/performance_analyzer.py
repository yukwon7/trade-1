from __future__ import annotations

from collections import defaultdict


class PerformanceAnalyzer:
    @staticmethod
    def summarize(rows) -> dict:
        pnls = [float(row["pnl"] or 0) for row in rows]
        wins = [value for value in pnls if value > 0]
        losses = [value for value in pnls if value < 0]
        gross_win = sum(wins)
        gross_loss = abs(sum(losses))
        equity = peak = drawdown = 0.0
        for value in reversed(pnls):
            equity += value
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
        count = len(pnls)
        return {
            "trades": count,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / count if count else 0.0,
            "profit_factor": gross_win / gross_loss if gross_loss else (999.0 if gross_win else 0.0),
            "expectancy": sum(pnls) / count if count else 0.0,
            "total_pnl": sum(pnls),
            "mdd": drawdown,
        }

    @staticmethod
    def grouped(rows, key: str) -> dict[str, dict]:
        buckets = defaultdict(list)
        for row in rows:
            buckets[str(row[key])].append(row)
        return {name: PerformanceAnalyzer.summarize(items) for name, items in buckets.items()}
