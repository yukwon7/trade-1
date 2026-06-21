from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from analytics.performance_analyzer import PerformanceAnalyzer

logger = logging.getLogger(__name__)


BOT_COMMANDS = [
    {"command": "status", "description": "봇 상태와 열린 포지션"},
    {"command": "positions", "description": "열린 포지션 상세"},
    {"command": "balance", "description": "모의투자 잔고와 증거금"},
    {"command": "daily", "description": "오늘 거래 성과"},
    {"command": "weekly", "description": "최근 7일 거래 성과"},
    {"command": "monthly", "description": "최근 30일 거래 성과"},
    {"command": "profit", "description": "전체 누적 손익"},
    {"command": "trades", "description": "최근 거래 내역"},
    {"command": "performance", "description": "심볼별 거래 성과"},
    {"command": "symbols", "description": "현재 모니터링 심볼"},
    {"command": "config", "description": "현재 거래 설정"},
    {"command": "count", "description": "포지션 슬롯 현황"},
    {"command": "pause", "description": "신규 진입 일시정지"},
    {"command": "resume", "description": "신규 진입 재개"},
    {"command": "stop", "description": "신규 진입 중지"},
    {"command": "start", "description": "신규 진입 시작"},
    {"command": "stake", "description": "리스크 기반 주문금액 확인"},
    {"command": "learn", "description": "오늘 거래 복기"},
    {"command": "learn_weekly", "description": "최근 7일 거래 복기"},
    {"command": "learn_monthly", "description": "최근 30일 거래 복기"},
    {"command": "help", "description": "전체 명령어 안내"},
]


class TelegramCommandHandler:
    def __init__(self, session, token: str, chat_id: str, notifier, trader, store, runtime):
        self.session = session
        self.chat_id = str(chat_id)
        self.notifier = notifier
        self.trader = trader
        self.store = store
        self.runtime = runtime
        self.api_url = f"https://api.telegram.org/bot{token}"
        self.offset = 0

    async def run(self, stop_event: asyncio.Event) -> None:
        backoff = 1
        configured = False
        while not stop_event.is_set():
            try:
                if not configured:
                    await self._configure()
                    configured = True
                    logger.info("telegram command polling started")
                result = await self._api(
                    "getUpdates",
                    {"offset": self.offset, "timeout": 25, "allowed_updates": ["message"]},
                    timeout=35,
                )
                for update in result:
                    self.offset = max(self.offset, int(update["update_id"]) + 1)
                    await self.handle_update(update)
                backoff = 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("telegram polling failed: %s", exc)
                configured = False
                await asyncio.sleep(backoff)
                backoff = min(30, backoff * 2)

    async def _configure(self) -> None:
        await self._api("deleteWebhook", {"drop_pending_updates": False})
        await self._api("setMyCommands", {"commands": BOT_COMMANDS})

    async def _api(self, method: str, payload: dict[str, Any], timeout: int = 15):
        async with self.session.post(
            f"{self.api_url}/{method}",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as response:
            data = await response.json(content_type=None)
            if response.status != 200 or not data.get("ok"):
                raise RuntimeError(f"Telegram {method} failed: HTTP {response.status} {data.get('description', '')}")
            return data.get("result")

    async def handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        text = message.get("text")
        if str(chat.get("id")) != self.chat_id or not isinstance(text, str) or not text.startswith("/"):
            return
        command, _, argument = text.strip().partition(" ")
        command = command[1:].split("@", 1)[0].lower()
        logger.info("telegram command received: /%s", command)
        try:
            reply = await self.dispatch(command, argument.strip())
        except Exception:
            logger.exception("telegram command failed: /%s", command)
            reply = "⚠️ 명령 처리 중 오류가 발생했습니다. 서버 로그를 확인하세요."
        if reply:
            await self.notifier.send(reply[:4000])

    async def dispatch(self, command: str, argument: str = "") -> str:
        if command in {"help", "menu"}:
            return self.help_text()
        if command in {"start", "resume"}:
            await self.trader.set_entry_paused(False)
            return "▶️ <b>신규 진입 재개</b>\n기존 포지션 관리와 신규 신호 진입이 모두 실행됩니다."
        if command in {"pause", "stop"}:
            await self.trader.set_entry_paused(True)
            return "⏸ <b>신규 진입 중지</b>\n열린 포지션의 손절·익절 관리는 계속 실행됩니다."
        if command == "status":
            return self._status_text()
        if command == "positions":
            return self._positions_text()
        if command == "balance":
            return await self._balance_text()
        if command == "profit":
            pnl = await self.store.account_pnl()
            return f"💰 <b>전체 누적 손익</b>\n{pnl:+.2f} USDT"
        if command == "count":
            return f"🧮 <b>포지션 슬롯</b>\n사용 {len(self.trader.positions)} / 최대 {self.trader.settings.max_open_positions}"
        if command == "symbols":
            symbols = self.runtime.current.symbols
            return f"🔎 <b>모니터링 심볼 {len(symbols)}개</b>\n{html.escape(', '.join(symbols))}"
        if command == "config":
            return self._config_text()
        if command == "stake":
            risk = self.trader.balance * self.trader.settings.risk_per_trade
            return (
                "🛡 <b>리스크 기반 주문금액</b>\n"
                f"거래당 최대 손실 예산: {risk:.2f} USDT "
                f"({self.trader.settings.risk_per_trade * 100:.2f}%)\n"
                "고정 증거금이 아니라 진입가와 ATR 손절 거리로 수량을 자동 계산합니다."
            )
        if command == "trades":
            return await self._recent_trades_text()
        if command == "performance":
            return await self._performance_text()
        if command in {"daily", "learn"}:
            return await self._period_text("오늘", timedelta(days=1), calendar_day=True, review=command == "learn")
        if command in {"weekly", "learn_weekly"}:
            return await self._period_text("최근 7일", timedelta(days=7), review=command.startswith("learn"))
        if command in {"monthly", "learn_monthly"}:
            return await self._period_text("최근 30일", timedelta(days=30), review=command.startswith("learn"))
        return f"❓ 지원하지 않는 명령입니다: /{html.escape(command)}\n/help에서 명령 목록을 확인하세요."

    def _status_text(self) -> str:
        state = "신규 진입 중지" if self.trader.entry_paused else "정상 실행"
        return (
            "🤖 <b>trade-1 상태</b>\n"
            f"상태: {state}\n"
            f"잔고: {self.trader.balance:.2f} USDT\n"
            f"포지션: {len(self.trader.positions)} / {self.trader.settings.max_open_positions}\n"
            f"모니터링: {len(self.runtime.current.symbols)}개\n\n"
            f"{self._positions_text(include_header=False)}"
        )

    def _positions_text(self, include_header: bool = True) -> str:
        if not self.trader.positions:
            body = "열린 포지션이 없습니다."
        else:
            lines = []
            for position in sorted(self.trader.positions.values(), key=lambda item: item.symbol):
                gross = (
                    (position.current_price - position.entry_price) * position.remaining_size
                    if position.direction == "LONG"
                    else (position.entry_price - position.current_price) * position.remaining_size
                )
                lines.append(
                    f"<b>{html.escape(position.symbol)}</b> {position.direction} {position.leverage}x\n"
                    f"진입 {position.entry_price:.6g} · 현재 {position.current_price:.6g}\n"
                    f"미실현(비용 전) {gross:+.2f} · SL {position.sl_price:.6g} · 추가 {position.add_count}/3"
                )
            body = "\n\n".join(lines)
        return f"📌 <b>열린 포지션</b>\n{body}" if include_header else body

    async def _balance_text(self) -> str:
        used_margin = sum(
            position.remaining_size * position.current_price / position.leverage
            for position in self.trader.positions.values()
        )
        pnl = await self.store.account_pnl()
        return (
            "💵 <b>모의투자 계좌</b>\n"
            f"현재 잔고: {self.trader.balance:.2f} USDT\n"
            f"누적 실현손익: {pnl:+.2f} USDT\n"
            f"사용 증거금: {used_margin:.2f} USDT\n"
            f"가용 추정액: {max(0.0, self.trader.balance - used_margin):.2f} USDT"
        )

    def _config_text(self) -> str:
        settings = self.trader.settings
        return (
            "⚙️ <b>현재 거래 설정</b>\n"
            f"최소 점수: {settings.min_score}\n"
            f"최대 레버리지: {settings.max_leverage}x\n"
            f"최대 포지션: {settings.max_open_positions}\n"
            f"거래당 리스크: {settings.risk_per_trade * 100:.2f}%\n"
            f"추가매수: {'사용' if settings.pyramiding_enabled else '중지'}\n"
            f"거래 빈도 배수: {settings.trade_frequency_multiplier:.2f}"
        )

    async def _recent_trades_text(self) -> str:
        rows = await self.store.recent_trades(10)
        if not rows:
            return "📜 <b>최근 거래</b>\n완료된 거래가 없습니다."
        lines = [
            f"{row['symbol']} {row['direction']} · {float(row['pnl'] or 0):+.2f} USDT · {html.escape(str(row['exit_reason'] or '-'))}"
            for row in rows
        ]
        return "📜 <b>최근 거래 10건</b>\n" + "\n".join(lines)

    async def _performance_text(self) -> str:
        rows = await self.store.performance_rows(1000)
        if not rows:
            return "📈 <b>심볼별 성과</b>\n완료된 거래가 없습니다."
        grouped = PerformanceAnalyzer.grouped(rows, "symbol")
        ordered = sorted(grouped.items(), key=lambda item: item[1]["total_pnl"], reverse=True)
        lines = [
            f"{html.escape(symbol)}: {metrics['trades']}회 · 승률 {metrics['win_rate'] * 100:.1f}% · {metrics['total_pnl']:+.2f}"
            for symbol, metrics in ordered[:15]
        ]
        return "📈 <b>심볼별 성과</b>\n" + "\n".join(lines)

    async def _period_text(self, label: str, period: timedelta, calendar_day: bool = False, review: bool = False) -> str:
        now = datetime.now(timezone.utc)
        since = datetime.combine(now.date(), datetime.min.time(), tzinfo=timezone.utc) if calendar_day else now - period
        rows = await self.store.trades_since(since.isoformat())
        metrics = PerformanceAnalyzer.summarize(rows)
        if not rows:
            return f"📊 <b>{label} {'복기' if review else '성과'}</b>\n완료된 거래가 없습니다."
        text = (
            f"📊 <b>{label} {'복기' if review else '성과'}</b>\n"
            f"거래 {metrics['trades']}회 · 승 {metrics['wins']} / 패 {metrics['losses']}\n"
            f"승률 {metrics['win_rate'] * 100:.1f}% · PF {metrics['profit_factor']:.2f}\n"
            f"손익 {metrics['total_pnl']:+.2f} USDT · MDD {metrics['mdd']:.2f} USDT"
        )
        if review:
            grouped = PerformanceAnalyzer.grouped(rows, "symbol")
            ordered = sorted(grouped.items(), key=lambda item: item[1]["total_pnl"], reverse=True)
            best = ordered[0]
            worst = ordered[-1]
            text += (
                f"\n최고: {html.escape(best[0])} {best[1]['total_pnl']:+.2f}"
                f"\n최저: {html.escape(worst[0])} {worst[1]['total_pnl']:+.2f}"
            )
        return text

    @staticmethod
    def help_text() -> str:
        return (
            "📚 <b>trade-1 명령어</b>\n"
            "/status /positions /balance /profit /count\n"
            "/daily /weekly /monthly /trades /performance\n"
            "/learn /learn_weekly /learn_monthly\n"
            "/symbols /config /stake\n"
            "/pause 또는 /stop — 신규 진입 중지\n"
            "/resume 또는 /start — 신규 진입 재개\n\n"
            "중지 상태에서도 열린 포지션의 손절·익절은 계속 관리합니다."
        )
