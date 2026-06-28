from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from config import Settings
from server_a.hermes.cache import JsonCache
from server_a.hermes.router import build_decision


def run_hermes_cycle(settings: Settings | None = None, persist: bool = True) -> dict:
    settings = settings or Settings.from_env()
    result = build_decision(settings, current_strategy_ids=_current_strategy_ids(settings.config_dir))
    generated_at = datetime.now(timezone.utc).isoformat()
    report = {
        "generated_at": generated_at,
        **result,
    }
    report["summary"] = _summary(report)
    if persist:
        settings.config_dir.mkdir(parents=True, exist_ok=True)
        JsonCache(settings.config_dir / "strategy_decision_report.json").write(report)
        if report["deployable"]:
            decision = report["decision"]
            JsonCache(settings.config_dir / "strategy_config.json").write(decision["strategy_config"])
            JsonCache(settings.config_dir / "risk_config.json").write(decision["risk_config"])
            _ensure_selected_symbols(settings.config_dir)
    return report


def _current_strategy_ids(config_dir: Path) -> list[str]:
    path = config_dir / "strategy_config.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    ids = data.get("active_strategy_ids") or ["MACD_RSI_MOMENTUM"]
    return [str(item) for item in ids]


def _ensure_selected_symbols(config_dir: Path) -> None:
    path = config_dir / "selected_symbols.json"
    if path.exists():
        return
    JsonCache(path).write({
        "symbols": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "hermes_default",
    })


def _summary(report: dict) -> str:
    performance = report["performance"]
    decision = report["decision"]
    return "\n".join([
        "HERMES_DECISION_REPORT",
        f"generated_at: {report['generated_at']}",
        f"action: {decision['action']}",
        f"deployable: {report['deployable']} ({report['gate_reason']})",
        f"reason: {decision['reason']}",
        f"trade_count: {performance['trade_count']}",
        f"net_pnl: {performance['net_pnl']:+.2f}",
        f"win_rate: {performance['win_rate']*100:.2f}%",
        f"profit_factor: {performance['profit_factor']:.2f}",
        f"max_drawdown: {performance['max_drawdown']*100:.2f}%",
    ])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args()
    report = run_hermes_cycle(persist=not args.no_persist)
    print(report["summary"])


if __name__ == "__main__":
    main()
