from __future__ import annotations

import asyncio
import html
import json
import logging
from typing import Any

import aiohttp

from execution.position_manager import summarize_positions

logger = logging.getLogger(__name__)


EXECUTION_BOT_COMMANDS = [
    {"command": "status", "description": "executor status"},
    {"command": "positions", "description": "open positions"},
    {"command": "risk", "description": "runtime risk config"},
    {"command": "pause", "description": "pause new entries"},
    {"command": "resume", "description": "resume new entries"},
    {"command": "close_all", "description": "paper emergency close with CONFIRM"},
    {"command": "config", "description": "active config"},
    {"command": "health", "description": "execution health"},
]


class TelegramExecutionCommandHandler:
    """Server B command bot. No analysis, backtest, stress test, or scanner calls."""

    def __init__(self, session, token: str, chat_id: str, notifier, trader, store, reloader):
        self.session = session
        self.chat_id = str(chat_id)
        self.notifier = notifier
        self.trader = trader
        self.store = store
        self.reloader = reloader
        self.api_url = f"https://api.telegram.org/bot{token}"
        self.offset = 0

    async def run(self, stop_event: asyncio.Event) -> None:
        configured = False
        backoff = 1
        while not stop_event.is_set():
            try:
                if not configured:
                    await self._api("deleteWebhook", {"drop_pending_updates": False})
                    await self._api("setMyCommands", {"commands": EXECUTION_BOT_COMMANDS})
                    configured = True
                    logger.info("telegram execution command polling started")
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
                logger.warning("telegram execution polling failed: %s", exc)
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
        logger.info("telegram execution command received: /%s", command)
        try:
            reply = await self.dispatch(command, argument.strip())
        except Exception:
            logger.exception("telegram execution command failed: /%s", command)
            reply = "⚠️ 명령 처리 중 오류가 발생했습니다. 서버 로그를 확인하세요."
        if reply:
            await self.notifier.send(reply[:4000])

    async def dispatch(self, command: str, argument: str = "") -> str:
        if command in {"start", "help"}:
            return self.help_text()
        if command == "status":
            return self._status_text()
        if command == "positions":
            return self._positions_text()
        if command == "risk":
            return self._risk_text()
        if command == "config":
            return self._config_text()
        if command == "health":
            return self._health_text()
        if command == "pause":
            await self.trader.set_entry_paused(True)
            return "⏸ <b>신규 진입 중지</b>\n기존 포지션 관리는 계속됩니다."
        if command == "resume":
            await self.trader.set_entry_paused(False)
            return "▶️ <b>신규 진입 재개</b>"
        if command == "close_all":
            if argument != "CONFIRM":
                return "확인을 위해 <code>/close_all CONFIRM</code> 를 입력하세요. 기존 포지션을 강제 종료합니다."
            closed = await self.trader.close_all("OPERATOR_CLOSE_ALL")
            return f"🚨 <b>전체 포지션 종료 요청 처리</b>\n종료 포지션: {closed}"
        return f"❓ 지원하지 않는 실행 명령입니다: /{html.escape(command)}"

    def _status_text(self) -> str:
        runtime = self.reloader.current()
        state = "신규 진입 중지" if self.trader.entry_paused else "정상 실행"
        return (
            "🤖 <b>Server B Executor</b>\n"
            f"상태: {state}\n"
            f"전략: {', '.join(runtime.strategy.active_strategy_ids)}\n"
            f"심볼: {len(runtime.symbols.symbols)}개\n"
            f"잔고: {self.trader.balance:.2f} USDT\n"
            f"포지션: {len(self.trader.positions)} / {runtime.risk.max_open_positions}"
        )

    def _positions_text(self) -> str:
        rows = summarize_positions(self.trader.positions)
        if not rows:
            return "📌 <b>열린 포지션</b>\n없음"
        lines = [
            f"{row['symbol']} {row['direction']} [{row['strategy_id']}] "
            f"{row['leverage']}x · PnL {row['unrealized_gross']:+.2f} · SL {row['stop_price']:.6g}"
            for row in rows
        ]
        return "📌 <b>열린 포지션</b>\n" + "\n".join(lines)

    def _risk_text(self) -> str:
        risk = self.reloader.current().risk
        return (
            "🛡 <b>Risk Config</b>\n"
            f"max_open_positions={risk.max_open_positions}\n"
            f"risk_per_trade={risk.risk_per_trade:.4f}\n"
            f"max_leverage={risk.max_leverage}x\n"
            f"daily_loss_limit={risk.daily_loss_limit:.2%}\n"
            f"weekly_drawdown_limit={risk.weekly_drawdown_limit:.2%}"
        )

    def _config_text(self) -> str:
        runtime = self.reloader.reload()
        errors = "\n".join(f"{k}: {html.escape(v)}" for k, v in self.reloader.last_errors.items()) or "없음"
        return (
            "⚙️ <b>Runtime Config</b>\n"
            f"mode={runtime.strategy.mode}\n"
            f"active={', '.join(runtime.strategy.active_strategy_ids)}\n"
            f"disabled={', '.join(runtime.strategy.disabled_strategy_ids) or '-'}\n"
            f"symbols={', '.join(runtime.symbols.symbols)}\n"
            f"errors={errors}"
        )

    def _health_text(self) -> str:
        path = self.trader.settings.config_dir / "execution_health.json"
        if not path.exists():
            return "🩺 <b>Execution Health</b>\n아직 health snapshot이 없습니다."
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "🩺 <b>Execution Health</b>\nhealth snapshot을 읽을 수 없습니다."
        return (
            "🩺 <b>Execution Health</b>\n"
            f"updated_at={html.escape(str(data.get('updated_at')))}\n"
            f"open_positions={data.get('open_positions')}\n"
            f"outcomes={html.escape(str(data.get('outcomes')))}\n"
            f"errors={html.escape(str(data.get('config_errors')))}"
        )

    @staticmethod
    def help_text() -> str:
        return (
            "📚 <b>Server B 실행 명령어</b>\n"
            "/status /positions /risk /pause /resume\n"
            "/close_all CONFIRM /config /health\n\n"
            "분석 명령(/stress, /backtest, /daily 등)은 Server A에서만 실행합니다."
        )
