from __future__ import annotations

from collections.abc import Sequence

from indicators import adx, atr, ema, rsi, volume_ratio
from models import Candle, Direction, IndicatorSnapshot, Signal
from strategy.score_engine import ScoreEngine


class SignalEngine:
    def __init__(self, support_resistance_lookback: int = 20):
        self.lookback = support_resistance_lookback

    def analyze(
        self,
        symbol: str,
        candles_1h: Sequence[Candle],
        candles_15m: Sequence[Candle],
        candles_5m: Sequence[Candle],
        minimum_score: int = 65,
    ) -> tuple[Signal | None, tuple[IndicatorSnapshot, IndicatorSnapshot, IndicatorSnapshot]]:
        snapshots = (
            self.snapshot(symbol, "1h", candles_1h),
            self.snapshot(symbol, "15m", candles_15m),
            self.snapshot(symbol, "5m", candles_5m),
        )
        one_hour, fifteen, five = snapshots
        direction = self._direction(one_hour, fifteen, five)
        if direction is None or five.adx < 20 or five.volume_ratio < 1.2:
            return None, snapshots
        breakout, retest = self._breakout(direction, five)
        if not breakout:
            return None, snapshots
        score, parts = ScoreEngine.calculate(direction, one_hour, fifteen, five, breakout, retest)
        if score < minimum_score:
            return None, snapshots
        signal = Signal(
            symbol=symbol,
            direction=direction,
            score=score,
            trend_score=parts["trend"],
            momentum_score=parts["momentum"],
            volume_score=parts["volume"],
            breakout_score=parts["breakout"],
            volatility_score=parts["volatility"],
            entry_price=five.close,
            atr=five.atr,
            adx=five.adx,
            rsi=five.rsi,
            ema20=five.ema20,
            ema50=five.ema50,
            volume_ratio=five.volume_ratio,
            reason=f"1H/15M trend + 5M {direction.lower()} breakout",
        )
        return signal, snapshots

    def snapshot(self, symbol: str, timeframe: str, candles: Sequence[Candle]) -> IndicatorSnapshot:
        if len(candles) < 60:
            raise ValueError(f"{symbol} {timeframe}: at least 60 closed candles required")
        closes = [item.close for item in candles]
        volumes = [item.volume for item in candles]
        ema20_values, ema50_values = ema(closes, 20), ema(closes, 50)
        rsi_values, adx_values, atr_values = rsi(closes, 14), adx(candles, 14), atr(candles, 14)
        volume_values = volume_ratio(volumes, 20)
        prior = candles[-(self.lookback + 1) : -1]
        support = min(item.low for item in prior)
        resistance = max(item.high for item in prior)
        recent_atr = [value for value in atr_values[-14:] if value > 0]
        atr_average = sum(recent_atr) / len(recent_atr) if recent_atr else 0.0
        last = candles[-1]
        return IndicatorSnapshot(
            symbol=symbol,
            timeframe=timeframe,
            close=last.close,
            ema20=ema20_values[-1],
            ema50=ema50_values[-1],
            rsi=rsi_values[-1],
            adx=adx_values[-1],
            atr=atr_values[-1],
            atr_average=atr_average,
            volume_ratio=volume_values[-1],
            support=support,
            resistance=resistance,
            previous_close=candles[-2].close,
            candle_high=last.high,
            candle_low=last.low,
        )

    @staticmethod
    def _direction(one_hour: IndicatorSnapshot, fifteen: IndicatorSnapshot, five: IndicatorSnapshot) -> Direction | None:
        if one_hour.ema20 > one_hour.ema50 and fifteen.ema20 > fifteen.ema50 and five.rsi > 50:
            return "LONG"
        if one_hour.ema20 < one_hour.ema50 and fifteen.ema20 < fifteen.ema50 and five.rsi < 50:
            return "SHORT"
        return None

    @staticmethod
    def _breakout(direction: Direction, five: IndicatorSnapshot) -> tuple[bool, bool]:
        if direction == "LONG":
            breakout = five.previous_close <= five.resistance < five.close
            retest = breakout and five.candle_low <= five.resistance and five.close > five.resistance
        else:
            breakout = five.previous_close >= five.support > five.close
            retest = breakout and five.candle_high >= five.support and five.close < five.support
        return breakout, retest
