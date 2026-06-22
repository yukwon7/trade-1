from __future__ import annotations

import asyncio
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiohttp

from config import Settings
from storage import SQLiteManager, TradeStore
from strategies import STRATEGIES


def _metrics(rows, initial_balance: float) -> dict:
    pnls = [float(row["pnl"] or 0.0) for row in rows]
    returns = [float(row["return_pct"] or 0.0) for row in rows]
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    gross_loss = abs(sum(losses))
    profit_factor = sum(wins) / gross_loss if gross_loss else (10.0 if wins else 0.0)
    equity = peak = initial_balance
    max_drawdown = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
    sharpe = 0.0
    if len(returns) >= 2:
        deviation = statistics.pstdev(returns)
        sharpe = statistics.mean(returns) / deviation if deviation > 0 else 0.0
    return {
        "net_pnl": sum(pnls),
        "win_rate": len(wins) / len(rows) if rows else 0.0,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe,
        "trade_count": len(rows),
    }


def _normalize(values: dict[str, float], inverse: bool = False) -> dict[str, float]:
    if not values:
        return {}
    low, high = min(values.values()), max(values.values())
    if math.isclose(low, high):
        return {key: 0.5 for key in values}
    output = {key: (value - low) / (high - low) for key, value in values.items()}
    return {key: 1.0 - value for key, value in output.items()} if inverse else output


class TournamentEvaluator:
    def __init__(self, settings: Settings, store: TradeStore):
        self.settings = settings
        self.store = store
        self.result_path = settings.config_dir / "tournament_result.json"

    async def evaluate(self, persist: bool = True) -> dict:
        rows = await self.store.strategy_rows()
        grouped: dict[str, list] = defaultdict(list)
        by_symbol: dict[tuple[str, str], list] = defaultdict(list)
        for row in rows:
            grouped[str(row["strategy_id"])].append(row)
            by_symbol[(str(row["strategy_id"]), str(row["symbol"]))].append(row)

        raw = {strategy_id: _metrics(grouped.get(strategy_id, []), self.settings.initial_balance) for strategy_id in STRATEGIES}
        evaluable = {key: value for key, value in raw.items() if value["trade_count"] >= 10}
        pf_norm = _normalize({key: min(5.0, value["profit_factor"]) for key, value in evaluable.items()})
        sharpe_norm = _normalize({key: max(-3.0, min(3.0, value["sharpe_ratio"])) for key, value in evaluable.items()})
        mdd_norm = _normalize({key: value["max_drawdown"] for key, value in evaluable.items()}, inverse=True)

        rankings = []
        for strategy_id, strategy in STRATEGIES.items():
            metrics = raw[strategy_id]
            score = 0.0
            if strategy_id in evaluable:
                score = (
                    metrics["win_rate"] * 0.25
                    + pf_norm[strategy_id] * 0.30
                    + sharpe_norm[strategy_id] * 0.25
                    + mdd_norm[strategy_id] * 0.20
                )
            eligible = (
                metrics["trade_count"] >= 10
                and metrics["win_rate"] >= 0.45
                and metrics["max_drawdown"] <= 0.15
                and metrics["profit_factor"] >= 1.1
            )
            symbol_metrics = {
                symbol: _metrics(by_symbol.get((strategy_id, symbol), []), self.settings.initial_balance)
                for symbol in self.settings.symbols
            }
            rankings.append({
                "strategy_id": strategy_id,
                "strategy_name": strategy.name,
                "score": round(max(0.0, min(1.0, score)), 6),
                "eligible": eligible,
                **metrics,
                "symbol_metrics": symbol_metrics,
            })
        rankings.sort(key=lambda item: (item["eligible"], item["score"], item["net_pnl"]), reverse=True)
        for rank, item in enumerate(rankings, 1):
            item["rank"] = rank

        candidates = [item for item in rankings if item["eligible"]]
        best = candidates[0] if candidates else None
        current = self._read_result()
        locked = current.get("locked_strategy") if current.get("locked_strategy") in STRATEGIES else None
        locked_at = self._parse_time(current.get("locked_at"))
        action, reason = "CONTINUE_EVALUATION", "no strategy passed all filters"
        now = datetime.now(timezone.utc)
        if best and not locked:
            locked = best["strategy_id"]
            locked_at = now
            action, reason = "LOCK", f"{locked} ranked first and passed all filters"
        elif best and locked:
            current_rank = next((item for item in rankings if item["strategy_id"] == locked), None)
            elapsed = now - (locked_at or now)
            threshold = (current_rank["score"] if current_rank else 0.0) * 1.10
            if best["strategy_id"] != locked and elapsed >= timedelta(hours=72) and best["score"] > threshold:
                previous = locked
                locked = best["strategy_id"]
                locked_at = now
                action, reason = "REPLACE", f"{locked} exceeded {previous} score by more than 10% after 72h"
            else:
                reason = f"locked strategy {locked} retained; replacement conditions not met"

        report = {
            "evaluated_at": now.isoformat(),
            "mode": self._current_mode(),
            "rankings": rankings,
            "best_strategy": best["strategy_id"] if best else None,
            "action": action,
            "reason": reason,
        }
        if persist:
            result = {
                "locked_strategy": locked,
                "locked_at": locked_at.isoformat() if locked_at else None,
                "last_evaluated_at": now.isoformat(),
                "best_strategy": report["best_strategy"],
                "action": action,
                "reason": reason,
            }
            self._atomic_write(result)
            await self.store.insert_report(report)
        return report

    def _read_result(self) -> dict:
        try:
            data = json.loads(self.result_path.read_text(encoding="utf-8")) if self.result_path.exists() else {}
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _current_mode(self) -> str:
        path = self.settings.config_dir / "tournament_control.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            mode = data.get("mode")
            return mode if mode in {"MODE_A", "MODE_B"} else self.settings.tournament_mode
        except (OSError, json.JSONDecodeError):
            return self.settings.tournament_mode

    def _atomic_write(self, result: dict) -> None:
        self.result_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.result_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(self.result_path)

    @staticmethod
    def _parse_time(value) -> datetime | None:
        try:
            return datetime.fromisoformat(value) if value else None
        except (TypeError, ValueError):
            return None


def report_text(report: dict) -> str:
    lines = [
        "🏆 <b>TOURNAMENT_REPORT</b>",
        f"평가: {report['evaluated_at']}",
        f"모드: {report['mode']}",
    ]
    for item in report["rankings"]:
        marker = "✅" if item["eligible"] else "⏳"
        lines.append(
            f"{item['rank']}. {item['strategy_id']} {marker} · 점수 {item['score']:.3f} · "
            f"승률 {item['win_rate'] * 100:.2f}% · PF {item['profit_factor']:.2f} · "
            f"MDD {item['max_drawdown'] * 100:.2f}% · {item['trade_count']}회"
        )
    lines.extend([
        f"BEST: {report.get('best_strategy') or '-'}",
        f"ACTION: {report['action']}",
        f"사유: {report['reason']}",
    ])
    return "\n".join(lines)


async def main() -> None:
    from notify.telegram_notify import TelegramNotifier

    settings = Settings.from_env()
    if settings.server_role != "analysis":
        raise RuntimeError("tournament evaluator may only run with SERVER_ROLE=analysis")
    manager = SQLiteManager(settings.database_path)
    await manager.initialize()
    store = TradeStore(manager)
    report = await TournamentEvaluator(settings, store).evaluate(persist=True)
    async with aiohttp.ClientSession() as session:
        await TelegramNotifier(session, settings.telegram_bot_token, settings.telegram_chat_id).send(report_text(report))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    await manager.close()


if __name__ == "__main__":
    asyncio.run(main())
