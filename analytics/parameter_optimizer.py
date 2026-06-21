from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
import aiohttp

from config import Settings
from storage import SQLiteManager, TradeStore
from analytics.performance_analyzer import PerformanceAnalyzer
from analytics.pattern_analyzer import PatternAnalyzer
from notify import TelegramNotifier


class ParameterOptimizer:
    def __init__(self, settings: Settings, store: TradeStore):
        self.settings = settings
        self.store = store
        self.path = settings.config_dir / "config_override.json"

    async def run(self) -> dict:
        rows = await self.store.performance_rows(1000)
        if len(rows) < 100:
            return {"skipped": True, "reason": "fewer than 100 closed trades", "trades": len(rows)}
        metrics = PerformanceAnalyzer.summarize(rows)
        patterns = PatternAnalyzer.analyze(rows)
        current = self._read_current()
        updated = dict(current)
        reasons: list[str] = []
        stability = dict(current.get("_stability", {}))
        if metrics["win_rate"] < 0.45:
            updated["MIN_SCORE"] = min(90, int(current.get("MIN_SCORE", self.settings.min_score)) + 5)
            reasons.append("win_rate_below_45")
            stability["win_rate_recovery_days"] = 0
        elif metrics["win_rate"] >= 0.55:
            stability["win_rate_recovery_days"] = int(stability.get("win_rate_recovery_days", 0)) + 1
            if stability["win_rate_recovery_days"] >= 3:
                updated["MIN_SCORE"] = max(self.settings.min_score, int(current.get("MIN_SCORE", self.settings.min_score)) - 5)
                stability["win_rate_recovery_days"] = 0
                reasons.append("win_rate_recovered_three_days")
        else:
            stability["win_rate_recovery_days"] = 0
        if metrics["profit_factor"] < 1.1:
            updated["TRADE_FREQUENCY_MULTIPLIER"] = max(0.2, float(current.get("TRADE_FREQUENCY_MULTIPLIER", 1.0)) * 0.8)
            reasons.append("profit_factor_below_1_1")
            stability["pf_recovery_days"] = 0
        elif metrics["profit_factor"] >= 1.3:
            stability["pf_recovery_days"] = int(stability.get("pf_recovery_days", 0)) + 1
            if stability["pf_recovery_days"] >= 3:
                updated["TRADE_FREQUENCY_MULTIPLIER"] = min(1.0, float(current.get("TRADE_FREQUENCY_MULTIPLIER", 1.0)) / 0.8)
                stability["pf_recovery_days"] = 0
                reasons.append("profit_factor_recovered_three_days")
        else:
            stability["pf_recovery_days"] = 0
        if metrics["mdd"] > self.settings.initial_balance * 0.08:
            updated["MAX_LEVERAGE"] = max(1, int(current.get("MAX_LEVERAGE", self.settings.max_leverage)) - 1)
            reasons.append("mdd_above_8_percent")
            stability["mdd_recovery_days"] = 0
        elif metrics["mdd"] < self.settings.initial_balance * 0.05:
            stability["mdd_recovery_days"] = int(stability.get("mdd_recovery_days", 0)) + 1
            if stability["mdd_recovery_days"] >= 3:
                updated["MAX_LEVERAGE"] = min(self.settings.max_leverage, int(current.get("MAX_LEVERAGE", self.settings.max_leverage)) + 1)
                stability["mdd_recovery_days"] = 0
                reasons.append("mdd_recovered_three_days")
        else:
            stability["mdd_recovery_days"] = 0
        recent_pyramided = [row for row in rows if int(row["add_count"] or 0) > 0][:5]
        if len(recent_pyramided) == 5 and all(float(row["pnl"] or 0) < 0 for row in recent_pyramided):
            updated["PYRAMIDING_ENABLED"] = False
            reasons.append("five_pyramiding_losses")
        updated.update({
            "_stability": stability,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "reason": ",".join(reasons) or "no_change",
        })
        self._atomic_write(updated)
        await self.store.log_optimizer(metrics, {"before": current, "after": updated, "patterns": patterns})
        return {"skipped": False, "metrics": metrics, "patterns": patterns, "before": current, "after": updated}

    def _read_current(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _atomic_write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(self.path)


async def main() -> None:
    settings = Settings.from_env()
    if settings.server_role != "analysis":
        raise RuntimeError("optimizer may only run with SERVER_ROLE=analysis")
    manager = SQLiteManager(settings.database_path)
    await manager.initialize()
    result = await ParameterOptimizer(settings, TradeStore(manager)).run()
    if not result.get("skipped") and result.get("before") != result.get("after"):
        async with aiohttp.ClientSession() as session:
            notifier = TelegramNotifier(session, settings.telegram_bot_token, settings.telegram_chat_id)
            await notifier.optimizer(result["before"], result["after"], result["after"].get("reason", "optimizer update"))
    print(json.dumps(result, indent=2, default=str))
    await manager.close()


if __name__ == "__main__":
    asyncio.run(main())
