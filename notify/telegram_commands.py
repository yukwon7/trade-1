from __future__ import annotations

import asyncio
import html
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from analytics.stress_tester import _metrics, run_stress_test, summary_text
from strategies import STRATEGIES

logger = logging.getLogger(__name__)


BOT_COMMANDS = [
    {"command": "status", "description": "봇과 현재 전략 상태"},
    {"command": "s", "description": "단축: 상태"},
    {"command": "router", "description": "차트 라우터 상태"},
    {"command": "r", "description": "단축: 라우터"},
    {"command": "regime", "description": "심볼별 차트 상태"},
    {"command": "g", "description": "단축: 차트 상태"},
    {"command": "strategy", "description": "전략 조회·선택·자동 전환"},
    {"command": "set", "description": "단축: 전략 선택"},
    {"command": "strategies", "description": "전략 카탈로그"},
    {"command": "cat", "description": "단축: 전략 카탈로그"},
    {"command": "stress", "description": "실거래 준비 스트레스 테스트"},
    {"command": "x", "description": "단축: 스트레스 테스트"},
    {"command": "positions", "description": "열린 포지션 상세"},
    {"command": "p", "description": "단축: 포지션"},
    {"command": "balance", "description": "모의투자 잔고와 증거금"},
    {"command": "b", "description": "단축: 잔고"},
    {"command": "daily", "description": "오늘 거래 성과"},
    {"command": "d", "description": "단축: 오늘 성과"},
    {"command": "weekly", "description": "최근 7일 거래 성과"},
    {"command": "w", "description": "단축: 주간 성과"},
    {"command": "monthly", "description": "최근 30일 거래 성과"},
    {"command": "m", "description": "단축: 월간 성과"},
    {"command": "trades", "description": "최근 거래 내역"},
    {"command": "t", "description": "단축: 최근 거래"},
    {"command": "pause", "description": "신규 진입 일시정지"},
    {"command": "pa", "description": "단축: 일시정지"},
    {"command": "resume", "description": "신규 진입 재개"},
    {"command": "go", "description": "단축: 재개"},
    {"command": "help", "description": "전체 명령어 안내"},
    {"command": "h", "description": "단축: 도움말"},
]


COMMAND_ALIASES = {
    "h": "help",
    "menu": "help",
    "s": "status",
    "r": "router",
    "g": "regime",
    "set": "strategy",
    "cat": "strategies",
    "x": "stress",
    "p": "positions",
    "pos": "positions",
    "b": "balance",
    "bal": "balance",
    "d": "daily",
    "w": "weekly",
    "m": "monthly",
    "t": "trades",
    "tr": "trades",
    "pa": "pause",
    "go": "resume",
}


class TelegramCommandHandler:
    def __init__(self, session, token: str, chat_id: str, notifier, trader, store, controller):
        self.session = session
        self.chat_id = str(chat_id)
        self.notifier = notifier
        self.trader = trader
        self.store = store
        self.controller = controller
        self.api_url = f"https://api.telegram.org/bot{token}"
        self.offset = 0

    async def run(self, stop_event: asyncio.Event) -> None:
        backoff, configured = 1, False
        while not stop_event.is_set():
            try:
                if not configured:
                    await self._api("deleteWebhook", {"drop_pending_updates": False})
                    await self._api("setMyCommands", {"commands": BOT_COMMANDS})
                    configured = True
                    logger.info("telegram command polling started")
                result = await self._api(
                    "getUpdates", {"offset": self.offset, "timeout": 25, "allowed_updates": ["message"]}, timeout=35
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

    async def _api(self, method: str, payload: dict[str, Any], timeout: int = 15):
        async with self.session.post(
            f"{self.api_url}/{method}", json=payload, timeout=aiohttp.ClientTimeout(total=timeout)
        ) as response:
            data = await response.json(content_type=None)
            if response.status != 200 or not data.get("ok"):
                raise RuntimeError(f"Telegram {method} failed: HTTP {response.status} {data.get('description', '')}")
            return data.get("result")

    async def handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message") or {}
        text = message.get("text")
        if str((message.get("chat") or {}).get("id")) != self.chat_id or not isinstance(text, str) or not text.startswith("/"):
            return
        raw, _, argument = text.strip().partition(" ")
        command = raw[1:].split("@", 1)[0].lower()
        logger.info("telegram command received: /%s", command)
        try:
            reply = await self.dispatch(command, argument.strip())
        except Exception:
            logger.exception("telegram command failed: /%s", command)
            reply = "⚠️ 명령 처리 중 오류가 발생했습니다. 서버 로그를 확인하세요."
        if reply:
            await self.notifier.send(reply[:4000])

    async def dispatch(self, command: str, argument: str = "") -> str:
        command = COMMAND_ALIASES.get(command, command)
        if command.startswith("s") and len(command) == 3 and command[1:].isdigit():
            return self._strategy_command(command.upper())
        if command in {"help"}:
            return self.help_text()
        if command in {"start", "resume"}:
            await self.trader.set_entry_paused(False)
            return "▶️ <b>신규 진입 재개</b>"
        if command in {"pause", "stop"}:
            await self.trader.set_entry_paused(True)
            return "⏸ <b>신규 진입 중지</b>\n열린 포지션의 청산 관리는 계속됩니다."
        if command == "strategy":
            return self._strategy_command(argument)
        if command == "router":
            return self._router_text()
        if command == "regime":
            return self._regime_text(argument)
        if command == "strategies":
            return self._strategies_text()
        if command == "stress":
            report = await asyncio.to_thread(run_stress_test, self.trader.settings, False)
            return "<pre>" + html.escape(summary_text(report)) + "</pre>"
        if command == "status":
            return self._status_text()
        if command == "positions":
            return self._positions_text()
        if command == "balance":
            return await self._balance_text()
        if command in {"profit", "performance"}:
            return await self._performance_text()
        if command == "count":
            return f"🧮 <b>포지션 슬롯</b>\n{len(self.trader.positions)} / {self.trader.settings.max_open_positions}"
        if command == "symbols":
            return f"🔎 <b>심볼 8개</b>\n{', '.join(self.trader.settings.symbols)}"
        if command in {"config", "stake"}:
            return self._config_text()
        if command == "trades":
            return await self._recent_trades_text()
        if command in {"daily", "learn"}:
            return await self._period_text("오늘", timedelta(days=1), calendar_day=True)
        if command in {"weekly", "learn_weekly"}:
            return await self._period_text("최근 7일", timedelta(days=7))
        if command in {"monthly", "learn_monthly"}:
            return await self._period_text("최근 30일", timedelta(days=30))
        return f"❓ 지원하지 않는 명령입니다: /{html.escape(command)}\n/help를 확인하세요."

    def _strategy_command(self, argument: str) -> str:
        value = argument.strip().upper()
        if not value:
            status = self.controller.status()
            return (
                "🎯 <b>현재 전략</b>\n"
                f"{status['active_strategy']} {html.escape(status['strategy_name'])}\n"
                f"선택 방식: {status['source']}\n"
                "\n"
                "변경: /strategy S99\n자동 복귀: /strategy auto"
            )
        if value == "AUTO":
            self.controller.set_manual_strategy(None)
            status = self.controller.status()
            return f"🔁 <b>자동 선택 복귀</b>\n현재 {status['active_strategy']} · 방식 {status['source']}"
        if value not in STRATEGIES:
            return "전략 ID는 S20~S55 또는 S99 중 하나여야 합니다. 예: /strategy S99"
        self.controller.set_manual_strategy(value)
        strategy = STRATEGIES[value]
        return (
            f"🎯 <b>수동 전략 고정</b>\n{value} {html.escape(strategy.name)} · {strategy.leverage}x\n"
            "기존 포지션은 진입 당시 전략으로 청산까지 관리됩니다."
        )

    def _status_text(self) -> str:
        strategy = self.controller.status()
        state = "신규 진입 중지" if self.trader.entry_paused else "정상 실행"
        router = self._read_router_snapshot()
        routed = ""
        if router:
            selected = sum(1 for item in router.get("decisions", {}).values() if item.get("selected_strategy"))
            routed = f"\n라우터: {selected}개 심볼 후보 선택 · /router"
        return (
            "🤖 <b>trade-1 차트 라우터</b>\n"
            f"상태: {state}\n"
            f"전략: {strategy['active_strategy']} {html.escape(strategy['strategy_name'])} ({strategy['source']})\n"
            f"잔고: {self.trader.balance:.2f} USDT\n"
            f"포지션: {len(self.trader.positions)} / {self.trader.settings.max_open_positions}{routed}\n\n"
            f"{self._positions_text(False)}"
        )

    def _positions_text(self, header: bool = True) -> str:
        if not self.trader.positions:
            body = "열린 포지션이 없습니다."
        else:
            lines = []
            for position in sorted(self.trader.positions.values(), key=lambda item: item.symbol):
                gross = (
                    (position.current_price - position.entry_price) * position.size
                    if position.direction == "LONG" else (position.entry_price - position.current_price) * position.size
                )
                lines.append(
                    f"<b>[{position.strategy_id}] {position.symbol}</b> {position.direction} {position.leverage}x\n"
                    f"진입 {position.entry_price:.6g} · 현재 {position.current_price:.6g}\n"
                    f"미실현(비용 전) {gross:+.2f} · SL {position.stop_price:.6g}"
                )
            body = "\n\n".join(lines)
        return f"📌 <b>열린 포지션</b>\n{body}" if header else body

    async def _balance_text(self) -> str:
        used = sum(position.margin for position in self.trader.positions.values())
        pnl = await self.store.account_pnl()
        return (
            "💵 <b>모의투자 계좌</b>\n"
            f"잔고 {self.trader.balance:.2f} · 누적손익 {pnl:+.2f} USDT\n"
            f"사용 증거금 {used:.2f} · 가용 추정 {max(0.0, self.trader.balance - used):.2f} USDT"
        )

    def _config_text(self) -> str:
        settings = self.trader.settings
        return (
            "⚙️ <b>라우터 리스크 설정</b>\n"
            f"거래당 최대 손실: {settings.risk_per_trade * 100:.1f}% ({self.trader.balance * settings.risk_per_trade:.2f} USDT)\n"
            f"전체 최대 포지션: {settings.max_open_positions}\n"
            f"최대 레버리지: {settings.max_leverage}x\n"
            "심볼당 포지션: 1개 · 일일 손실 한도: 5%"
        )

    async def _recent_trades_text(self) -> str:
        rows = await self.store.recent_trades(10)
        if not rows:
            return "📜 <b>최근 거래</b>\n완료된 거래가 없습니다."
        lines = [
            f"[{row['strategy_id']}] {row['symbol']} {row['direction']} · {float(row['pnl']):+.2f} · {html.escape(row['exit_reason'])}"
            for row in rows
        ]
        return "📜 <b>최근 거래 10건</b>\n" + "\n".join(lines)

    async def _performance_text(self) -> str:
        rows = await self.store.strategy_rows()
        if not rows:
            return "📈 <b>전략별 성과</b>\n완료된 거래가 없습니다."
        lines = []
        for strategy_id in STRATEGIES:
            selected = [row for row in rows if row["strategy_id"] == strategy_id]
            metrics = _metrics(selected, self.trader.settings.initial_balance)
            lines.append(
                f"{strategy_id}: {metrics['trade_count']}회 · 승률 {metrics['win_rate']*100:.1f}% · {metrics['net_pnl']:+.2f}"
            )
        return "📈 <b>전략별 성과</b>\n" + "\n".join(lines)

    async def _period_text(self, label: str, period: timedelta, calendar_day: bool = False) -> str:
        now = datetime.now(timezone.utc)
        since = datetime.combine(now.date(), datetime.min.time(), tzinfo=timezone.utc) if calendar_day else now - period
        rows = await self.store.trades_since(since.isoformat())
        metrics = _metrics(rows, self.trader.settings.initial_balance)
        return (
            f"📊 <b>{label} 성과</b>\n"
            f"거래 {metrics['trade_count']}회 · 승률 {metrics['win_rate']*100:.2f}%\n"
            f"PnL {metrics['net_pnl']:+.2f} · PF {metrics['profit_factor']:.2f}\n"
            f"MDD {metrics['max_drawdown']*100:.2f}% · Sharpe {metrics['sharpe_ratio']:.2f}"
        )

    def _router_text(self) -> str:
        snapshot = self._read_router_snapshot()
        if not snapshot:
            return "🧭 <b>차트 라우터</b>\n아직 라우터 스냅샷이 없습니다. 다음 5분봉 사이클 이후 다시 확인하세요."
        decisions = snapshot.get("decisions", {})
        lines = [
            "🧭 <b>차트 라우터</b>",
            f"업데이트: {html.escape(str(snapshot.get('updated_at', '-')))}",
            f"결과: {html.escape(str(snapshot.get('outcomes', {})))}",
            f"포지션: {snapshot.get('open_positions', 0)}",
        ]
        for symbol, item in sorted(decisions.items()):
            selected = item.get("selected_strategy") or "-"
            lines.append(
                f"{symbol}: {item.get('regime')} · {item.get('bias')} · "
                f"{item.get('outcome')} · {selected}"
            )
        return "\n".join(lines)

    def _regime_text(self, argument: str = "") -> str:
        snapshot = self._read_router_snapshot()
        if not snapshot:
            return "📉 <b>차트 상태</b>\n아직 분석 스냅샷이 없습니다."
        decisions = snapshot.get("decisions", {})
        symbol = argument.strip().upper()
        if symbol:
            item = decisions.get(symbol)
            if not item:
                return f"📉 <b>{html.escape(symbol)}</b>\n최근 라우터 분석 기록이 없습니다."
            return self._format_regime(symbol, item)
        return "📉 <b>심볼별 차트 상태</b>\n" + "\n".join(
            f"{symbol}: {item.get('regime')} · {item.get('bias')} · {', '.join(item.get('tags', [])) or '-'}"
            for symbol, item in sorted(decisions.items())
        )

    @staticmethod
    def _format_regime(symbol: str, item: dict[str, Any]) -> str:
        top = item.get("top_candidates") or []
        candidates = "\n".join(
            f"{candidate['strategy_id']} {html.escape(candidate['name'])} {candidate['direction']} {candidate['score']}"
            for candidate in top
        ) or "-"
        return (
            f"📉 <b>{html.escape(symbol)} 차트 상태</b>\n"
            f"레짐: {item.get('regime')} · 바이어스: {item.get('bias')}\n"
            f"추세: {item.get('trend')} · 변동성: {item.get('volatility')} · 거래량: {item.get('volume')}\n"
            f"태그: {', '.join(item.get('tags', [])) or '-'}\n"
            f"선택: {item.get('selected_strategy') or '-'} {html.escape(str(item.get('selected_name') or ''))}\n"
            f"후보:\n{candidates}"
        )

    @staticmethod
    def _strategies_text() -> str:
        catalog = [key for key in STRATEGIES if key.startswith("S") and key[1:].isdigit() and 20 <= int(key[1:]) <= 55]
        return (
            "🧩 <b>전략 카탈로그</b>\n"
            f"자동 라우터: S99 · {html.escape(STRATEGIES['S99'].name)}\n"
            f"차트 적응 전략: {len(catalog)}개 ({catalog[0]}~{catalog[-1]})\n"
            "현재 운영 권장: /strategy S99\n"
            "심볼별 실제 선택 전략: /router 또는 /regime BTCUSDT"
        )

    def _read_router_snapshot(self) -> dict[str, Any]:
        path = self.trader.settings.config_dir / "router_snapshot.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def help_text() -> str:
        return (
            "📚 <b>차트 라우터 명령어</b>\n"
            "/s = /status\n/r = /router\n/g = /regime\n/g BTCUSDT = /regime BTCUSDT\n"
            "/set S99 = /strategy S99\n/s99 = /strategy S99\n/cat = /strategies\n/x = /stress\n"
            "/p = /positions\n/b = /balance\n/t = /trades\n/d = /daily\n/w = /weekly\n/m = /monthly\n"
            "/pa = /pause\n/go = /resume\n/h = /help\n\n"
            "수동 전환 시 기존 포지션은 원래 전략으로 계속 관리됩니다."
        )
