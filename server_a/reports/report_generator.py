from __future__ import annotations


def decision_report_text(report: dict) -> str:
    return str(report.get("summary") or "")
