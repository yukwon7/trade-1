from __future__ import annotations

from models import Direction, IndicatorSnapshot


class ScoreEngine:
    @staticmethod
    def calculate(
        direction: Direction,
        one_hour: IndicatorSnapshot,
        fifteen_minute: IndicatorSnapshot,
        five_minute: IndicatorSnapshot,
        breakout: bool,
        retest: bool,
    ) -> tuple[int, dict[str, int]]:
        if five_minute.adx < 20:
            return 0, {"trend": 0, "momentum": 0, "volume": 0, "breakout": 0, "volatility": 0}

        bullish = direction == "LONG"
        one_hour_aligned = one_hour.ema20 > one_hour.ema50 if bullish else one_hour.ema20 < one_hour.ema50
        fifteen_aligned = fifteen_minute.ema20 > fifteen_minute.ema50 if bullish else fifteen_minute.ema20 < fifteen_minute.ema50
        trend = (10 if one_hour_aligned else 0) + (10 if fifteen_aligned else 0) + (10 if five_minute.adx >= 25 else 0)
        momentum = ScoreEngine._momentum(direction, five_minute.rsi)
        volume = 20 if five_minute.volume_ratio > 2.0 else 15 if five_minute.volume_ratio >= 1.5 else 10 if five_minute.volume_ratio >= 1.2 else 0
        breakout_score = (10 if breakout else 0) + (10 if retest else 0)
        atr_ratio = five_minute.atr / five_minute.atr_average if five_minute.atr_average > 0 else 0
        volatility = 10 if 0.8 <= atr_ratio <= 1.5 else 0
        parts = {"trend": trend, "momentum": momentum, "volume": volume, "breakout": breakout_score, "volatility": volatility}
        return sum(parts.values()), parts

    @staticmethod
    def _momentum(direction: Direction, value: float) -> int:
        if direction == "LONG":
            if 50 <= value < 60:
                return 10
            if 60 <= value <= 70:
                return 15
            if value > 70:
                return 5
        else:
            if 40 < value <= 50:
                return 10
            if 30 <= value <= 40:
                return 15
            if value < 30:
                return 5
        return 0
