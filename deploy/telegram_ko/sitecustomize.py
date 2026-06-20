"""Korean output patch for Freqtrade's built-in Telegram RPC.

Command names stay unchanged so upstream handlers remain compatible.  Only text
sent to Telegram is translated.  Loaded automatically through PYTHONPATH.
"""

from __future__ import annotations

from freqtrade.rpc.telegram import Telegram


_REPLACEMENTS = (
    ("Dry run is enabled. All trades are simulated.", "모의투자가 활성화되어 있습니다. 모든 거래는 가상 체결입니다."),
    ("Simulated balances in Dry Mode.", "모의투자 잔고입니다."),
    ("No open trade found.", "열린 포지션이 없습니다."),
    ("No active locks.", "활성화된 거래 잠금이 없습니다."),
    ("No trades yet.", "아직 거래 내역이 없습니다."),
    ("No closed trade", "종료된 거래 없음"),
    ("New Trade filled", "신규 포지션 체결"),
    ("New Trade", "신규 포지션"),
    ("Increasing position", "포지션 추가 진입"),
    ("Position increase filled", "추가 진입 체결"),
    ("Partially exited", "부분 청산 완료"),
    ("Partially exiting", "부분 청산 중"),
    ("Exited", "청산 완료"),
    ("Exiting", "청산 중"),
    ("Cancelling enter Order", "진입 주문 취소"),
    ("Cancelling exit Order", "청산 주문 취소"),
    ("Searching for USDT pairs to buy and sell based on", "다음 페어 목록에서 매수·매도 신호를 탐색합니다:"),
    ("Bot Control", "봇 제어"),
    ("Current state", "현재 상태"),
    ("Statistics", "통계"),
    ("Starts the trader", "거래 봇 시작"),
    ("Stops the trader", "거래 봇 중지"),
    ("This help message", "이 도움말 표시"),
    ("Show version", "버전 표시"),
    ("Lists all open trades", "열린 포지션 전체 표시"),
    ("Lists cumulative profit from all finished trades", "종료된 모든 거래의 누적 수익 표시"),
    ("Show bot managed balance per currency", "봇이 관리하는 통화별 잔고 표시"),
    ("Show account balance per currency", "계정의 통화별 전체 잔고 표시"),
    ("Show number of active trades compared to allowed number of trades", "현재 포지션 수와 허용 포지션 수 표시"),
    ("Show running configuration", "실행 중인 설정 표시"),
    ("Show currently locked pairs", "현재 잠긴 페어 표시"),
    ("Show performance of each finished trade grouped by pair", "페어별 종료 거래 성과 표시"),
    ("Warning", "경고"),
    ("ERROR", "오류"),
    ("Status", "상태"),
    ("Exchange", "거래소"),
    ("Stake per trade", "포지션당 증거금"),
    ("Minimum ROI", "최소 목표수익률"),
    ("Trailing Stoploss", "추적 손절"),
    ("Stoploss distance", "손절가까지 거리"),
    ("Initial Stoploss", "초기 손절가"),
    ("Stoploss", "손절"),
    ("Position adjustment", "포지션 추가 진입"),
    ("Timeframe", "타임프레임"),
    ("Strategy", "전략"),
    ("Trade ID", "거래 ID"),
    ("Current Pair", "현재 페어"),
    ("Pair", "페어"),
    ("Enter Tag", "진입 태그"),
    ("Exit Reason", "청산 사유"),
    ("Direction", "방향"),
    ("Amount", "수량"),
    ("Total invested", "총 투자금"),
    ("Open Rate", "진입 가격"),
    ("Current Rate", "현재 가격"),
    ("Close Rate", "종료 가격"),
    ("Exit Rate", "청산 가격"),
    ("Open Date", "진입 시각"),
    ("Close Date", "종료 시각"),
    ("Unrealized Profit", "미실현 손익"),
    ("Realized Profit", "실현 손익"),
    ("Cumulative Profit", "누적 손익"),
    ("Final Profit", "최종 손익"),
    ("Total Profit", "총손익"),
    ("Close Profit", "종료 손익"),
    ("Profit factor", "수익 팩터"),
    ("Profit", "손익"),
    ("Liquidation", "청산가"),
    ("Duration", "보유 시간"),
    ("Remaining", "잔여 금액"),
    ("Starting capital", "시작 자본"),
    ("Available", "사용 가능"),
    ("Balance", "잔고"),
    ("Pending", "주문 중"),
    ("Bot Owned", "봇 소유"),
    ("Estimated Value", "추정 가치"),
    ("Total Trade Count", "총 거래 수"),
    ("Bot started", "봇 시작"),
    ("First Trade opened", "첫 거래 진입"),
    ("Latest Trade opened", "최근 거래 진입"),
    ("Win / Loss", "승 / 패"),
    ("Winrate", "승률"),
    ("Avg. Duration", "평균 보유 시간"),
    ("Best Performing", "최고 성과"),
    ("Trading volume", "거래량"),
    ("Max Drawdown", "최대 낙폭"),
    ("Current Drawdown", "현재 낙폭"),
    ("Long", "롱"),
    ("Short", "숏"),
    ("running", "실행 중"),
    ("stopped", "중지됨"),
)


def _translate_ko(message: str) -> str:
    for source, target in _REPLACEMENTS:
        message = message.replace(source, target)
    return message


_original_send_msg = Telegram._send_msg


async def _send_msg_ko(self, msg: str, *args, **kwargs):
    if isinstance(msg, str):
        msg = _translate_ko(msg)
    return await _original_send_msg(self, msg, *args, **kwargs)


Telegram._send_msg = _send_msg_ko
