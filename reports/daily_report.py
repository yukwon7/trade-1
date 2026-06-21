from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import aiohttp

from analytics.performance_analyzer import PerformanceAnalyzer
from config import Settings
from models import utc_now_iso
from notify import TelegramNotifier
from storage import SQLiteManager, TradeStore


class DailyReporter:
    def __init__(self, store: TradeStore):
        self.store = store

    async def generate(self) -> tuple[dict, str]:
        rows = await self.store.performance_rows(1000)
        today = datetime.now(timezone.utc).date().isoformat()
        daily_rows = [row for row in rows if str(row["exit_time"]).startswith(today)]
        metrics = PerformanceAnalyzer.summarize(daily_rows)
        db = await self.store.manager.connect()
        await db.execute(
            """INSERT INTO daily_stats
               (date,total_trades,win_trades,loss_trades,win_rate,profit_factor,total_pnl,max_dd,created_at)
               VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(date) DO UPDATE SET
               total_trades=excluded.total_trades,win_trades=excluded.win_trades,
               loss_trades=excluded.loss_trades,win_rate=excluded.win_rate,
               profit_factor=excluded.profit_factor,total_pnl=excluded.total_pnl,max_dd=excluded.max_dd,
               created_at=excluded.created_at""",
            (today, metrics["trades"], metrics["wins"], metrics["losses"], metrics["win_rate"], metrics["profit_factor"], metrics["total_pnl"], metrics["mdd"], utc_now_iso()),
        )
        await db.commit()
        text = (
            f"날짜 {today}\n거래 {metrics['trades']}회 · 승률 {metrics['win_rate']*100:.1f}%\n"
            f"PnL {metrics['total_pnl']:+.2f} USDT · PF {metrics['profit_factor']:.2f} · MDD {metrics['mdd']:.2f}"
        )
        return metrics, text


async def main() -> None:
    settings = Settings.from_env()
    manager = SQLiteManager(settings.database_path)
    await manager.initialize()
    store = TradeStore(manager)
    _, report = await DailyReporter(store).generate()
    async with aiohttp.ClientSession() as session:
        await TelegramNotifier(session, settings.telegram_bot_token, settings.telegram_chat_id).daily_report(report)
    print(report)
    await manager.close()


if __name__ == "__main__":
    asyncio.run(main())
