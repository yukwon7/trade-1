from __future__ import annotations

import html
import logging

import aiohttp

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, session: aiohttp.ClientSession, token: str, chat_id: str):
        self.session = session
        self.chat_id = chat_id
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"

    async def send(self, text: str) -> bool:
        try:
            async with self.session.post(
                self.url,
                json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    logger.warning("telegram send failed: HTTP %d", response.status)
                    return False
                return True
        except (aiohttp.ClientError, TimeoutError) as exc:
            logger.warning("telegram send failed: %s", exc)
            return False

    async def startup(self, role: str, symbols: int) -> None:
        await self.send(f"🤖 <b>trade-1 시작</b>\n역할: {html.escape(role)}\n모니터링: {symbols}개")

    async def entry(self, position) -> None:
        await self.send(
            f"📥 <b>진입</b> {position.symbol} {position.direction}\n"
            f"가격 {position.entry_price:.6g} · {position.leverage}x · 점수 {position.score}\n"
            f"SL {position.sl_price:.6g} · 2R {position.tp_price:.6g}"
        )

    async def pyramid(self, position, price: float, quantity: float) -> None:
        await self.send(f"➕ <b>추가매수 {position.add_count}/3</b> {position.symbol}\n가격 {price:.6g} · 수량 {quantity:.6g} · 평단 {position.entry_price:.6g}")

    async def partial_close(self, position, price: float, quantity: float, pnl: float) -> None:
        await self.send(f"✂️ <b>50% 부분청산</b> {position.symbol}\n가격 {price:.6g} · 실현 PnL {pnl:+.2f} USDT")

    async def closed(self, position, price: float, pnl: float, reason: str) -> None:
        await self.send(f"📤 <b>전체청산</b> {position.symbol}\n가격 {price:.6g} · PnL {pnl:+.2f} USDT\n사유 {html.escape(reason)}")

    async def daily_report(self, report: str) -> None:
        await self.send(f"📊 <b>일일 리포트</b>\n{html.escape(report)}")

    async def optimizer(self, before: dict, after: dict, reason: str) -> None:
        await self.send(f"🧠 <b>최적화</b>\n{html.escape(str(before))} → {html.escape(str(after))}\n{html.escape(reason)}")

    async def symbols_changed(self, before: list[str], after: list[str]) -> None:
        await self.send(f"🔄 <b>심볼 교체</b>\n이전: {html.escape(', '.join(before))}\n현재: {html.escape(', '.join(after))}")

    async def circuit_breaker(self, reason: str, resume_at: str) -> None:
        await self.send(f"🛑 <b>Circuit Breaker</b>\n사유: {html.escape(reason)}\n재개: {html.escape(resume_at)}")

    async def error(self, message: str) -> None:
        await self.send(f"⚠️ <b>오류</b>\n{html.escape(message[:1000])}")
