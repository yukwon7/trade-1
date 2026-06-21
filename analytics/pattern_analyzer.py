from __future__ import annotations

from analytics.performance_analyzer import PerformanceAnalyzer


class PatternAnalyzer:
    @staticmethod
    def analyze(rows) -> dict:
        return {
            "by_symbol": PerformanceAnalyzer.grouped(rows, "symbol"),
            "by_direction": PerformanceAnalyzer.grouped(rows, "direction"),
            "by_leverage": PerformanceAnalyzer.grouped(rows, "leverage"),
            "pyramided": PerformanceAnalyzer.summarize([row for row in rows if int(row["add_count"] or 0) > 0]),
        }
