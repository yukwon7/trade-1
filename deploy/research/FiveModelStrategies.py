"""Five distinct futures strategy candidates for controlled comparison.

Research inspirations:
- Freqtrade FSupertrendStrategy and BbandRsi examples (GPL-3.0)
- Time-series momentum / moving-average trend following
- Donchian-style channel breakout

All candidates intentionally share leverage and risk management so the
backtest compares signal models rather than five unrelated money-management
schemes.  These are dry-run research strategies, not profit guarantees.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import talib.abstract as ta
from pandas import DataFrame

import freqtrade.vendor.qtpylib.indicators as qtpylib
from freqtrade.strategy import IStrategy


class _ResearchBase(IStrategy):
    INTERFACE_VERSION = 3
    can_short = True
    timeframe = "15m"
    startup_candle_count = 240
    process_only_new_candles = True
    position_adjustment_enable = False

    # Common risk controls for a fair signal-model comparison at 5x.
    minimal_roi = {"0": 0.02, "60": 0.012, "180": 0.0}
    stoploss = -0.03
    trailing_stop = True
    trailing_stop_positive = 0.008
    trailing_stop_positive_offset = 0.015
    trailing_only_offset_is_reached = True
    use_exit_signal = True
    exit_profit_only = False

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        return min(5.0, max_leverage)


class ModelEmaAdxTrend(_ResearchBase):
    """Fast/slow EMA trend with ADX strength and RSI direction filters."""

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            qtpylib.crossed_above(dataframe["ema20"], dataframe["ema50"])
            & (dataframe["close"] > dataframe["ema200"])
            & (dataframe["adx"] > 22)
            & (dataframe["rsi"].between(52, 72))
            & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "ema_adx_long")
        dataframe.loc[
            qtpylib.crossed_below(dataframe["ema20"], dataframe["ema50"])
            & (dataframe["close"] < dataframe["ema200"])
            & (dataframe["adx"] > 22)
            & (dataframe["rsi"].between(28, 48))
            & (dataframe["volume"] > 0),
            ["enter_short", "enter_tag"],
        ] = (1, "ema_adx_short")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            qtpylib.crossed_below(dataframe["ema20"], dataframe["ema50"]),
            ["exit_long", "exit_tag"],
        ] = (1, "ema_cross_exit")
        dataframe.loc[
            qtpylib.crossed_above(dataframe["ema20"], dataframe["ema50"]),
            ["exit_short", "exit_tag"],
        ] = (1, "ema_cross_exit")
        return dataframe


class ModelBollingerRsiReversion(_ResearchBase):
    """Bollinger/RSI mean reversion, restricted to non-trending regimes."""

    startup_candle_count = 60

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        bands = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2.2)
        dataframe["bb_lower"] = bands["lower"]
        dataframe["bb_mid"] = bands["mid"]
        dataframe["bb_upper"] = bands["upper"]
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["close"].shift(1) < dataframe["bb_lower"].shift(1))
            & (dataframe["close"] > dataframe["bb_lower"])
            & (dataframe["rsi"] < 42)
            & (dataframe["rsi"] > dataframe["rsi"].shift(1))
            & (dataframe["adx"] < 35)
            & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "bb_rsi_long")
        dataframe.loc[
            (dataframe["close"].shift(1) > dataframe["bb_upper"].shift(1))
            & (dataframe["close"] < dataframe["bb_upper"])
            & (dataframe["rsi"] > 58)
            & (dataframe["rsi"] < dataframe["rsi"].shift(1))
            & (dataframe["adx"] < 35)
            & (dataframe["volume"] > 0),
            ["enter_short", "enter_tag"],
        ] = (1, "bb_rsi_short")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["close"] >= dataframe["bb_mid"]) | (dataframe["rsi"] > 55),
            ["exit_long", "exit_tag"],
        ] = (1, "mean_revert_exit")
        dataframe.loc[
            (dataframe["close"] <= dataframe["bb_mid"]) | (dataframe["rsi"] < 45),
            ["exit_short", "exit_tag"],
        ] = (1, "mean_revert_exit")
        return dataframe


class ModelDonchianAtrBreakout(_ResearchBase):
    """Donchian breakout with ATR, ADX, and relative-volume confirmation."""

    startup_candle_count = 80

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["donchian_high"] = dataframe["high"].rolling(24).max().shift(1)
        dataframe["donchian_low"] = dataframe["low"].rolling(24).min().shift(1)
        dataframe["exit_high"] = dataframe["high"].rolling(10).max().shift(1)
        dataframe["exit_low"] = dataframe["low"].rolling(10).min().shift(1)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["volume_mean"] = dataframe["volume"].rolling(24).mean()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        liquid_move = (dataframe["volume"] > dataframe["volume_mean"] * 1.05) & (
            dataframe["atr_pct"] > 0.0015
        )
        dataframe.loc[
            (dataframe["close"] > dataframe["donchian_high"])
            & (dataframe["adx"] > 20)
            & liquid_move,
            ["enter_long", "enter_tag"],
        ] = (1, "donchian_long")
        dataframe.loc[
            (dataframe["close"] < dataframe["donchian_low"])
            & (dataframe["adx"] > 20)
            & liquid_move,
            ["enter_short", "enter_tag"],
        ] = (1, "donchian_short")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            dataframe["close"] < dataframe["exit_low"],
            ["exit_long", "exit_tag"],
        ] = (1, "channel_exit")
        dataframe.loc[
            dataframe["close"] > dataframe["exit_high"],
            ["exit_short", "exit_tag"],
        ] = (1, "channel_exit")
        return dataframe


class ModelMacdMomentum(_ResearchBase):
    """MACD impulse aligned with a long-term EMA and directional momentum."""

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]
        dataframe["macdhist"] = macd["macdhist"]
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            qtpylib.crossed_above(dataframe["macd"], dataframe["macdsignal"])
            & (dataframe["macdhist"] > 0)
            & (dataframe["close"] > dataframe["ema200"])
            & (dataframe["rsi"].between(50, 70))
            & (dataframe["adx"] > 18)
            & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "macd_momentum_long")
        dataframe.loc[
            qtpylib.crossed_below(dataframe["macd"], dataframe["macdsignal"])
            & (dataframe["macdhist"] < 0)
            & (dataframe["close"] < dataframe["ema200"])
            & (dataframe["rsi"].between(30, 50))
            & (dataframe["adx"] > 18)
            & (dataframe["volume"] > 0),
            ["enter_short", "enter_tag"],
        ] = (1, "macd_momentum_short")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            qtpylib.crossed_below(dataframe["macd"], dataframe["macdsignal"]),
            ["exit_long", "exit_tag"],
        ] = (1, "macd_cross_exit")
        dataframe.loc[
            qtpylib.crossed_above(dataframe["macd"], dataframe["macdsignal"]),
            ["exit_short", "exit_tag"],
        ] = (1, "macd_cross_exit")
        return dataframe


class ModelMacdMomentumLoose(ModelMacdMomentum):
    """Looser 15m candidate for more entries without 5m fee churn."""

    entry_adx_threshold = 15
    trend_ema_period = 100

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]
        dataframe["macdhist"] = macd["macdhist"]
        dataframe["trend_ema"] = ta.EMA(dataframe, timeperiod=self.trend_ema_period)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            qtpylib.crossed_above(dataframe["macd"], dataframe["macdsignal"])
            & (dataframe["close"] > dataframe["trend_ema"])
            & (dataframe["rsi"].between(45, 74))
            & (dataframe["adx"] > self.entry_adx_threshold)
            & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "macd_loose_long")
        dataframe.loc[
            qtpylib.crossed_below(dataframe["macd"], dataframe["macdsignal"])
            & (dataframe["close"] < dataframe["trend_ema"])
            & (dataframe["rsi"].between(26, 55))
            & (dataframe["adx"] > self.entry_adx_threshold)
            & (dataframe["volume"] > 0),
            ["enter_short", "enter_tag"],
        ] = (1, "macd_loose_short")
        return dataframe


class ModelMacdMomentumLoose18(ModelMacdMomentumLoose):
    entry_adx_threshold = 18


class ModelMacdMomentumLoose22(ModelMacdMomentumLoose):
    entry_adx_threshold = 22


class ModelMacdMomentumLoose150(ModelMacdMomentumLoose):
    trend_ema_period = 150


class ModelMacdMomentumLoose200(ModelMacdMomentumLoose):
    trend_ema_period = 200


class ModelMacdMomentumActive(_ResearchBase):
    """Balanced 5m MACD crossover with configurable trend-strength filter."""

    timeframe = "5m"
    entry_adx_threshold = 18

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]
        dataframe["macdhist"] = macd["macdhist"]
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            qtpylib.crossed_above(dataframe["macd"], dataframe["macdsignal"])
            & (dataframe["macdhist"] > 0)
            & (dataframe["close"] > dataframe["ema200"])
            & (dataframe["rsi"].between(50, 70))
            & (dataframe["adx"] > self.entry_adx_threshold)
            & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "macd_active_long")
        dataframe.loc[
            qtpylib.crossed_below(dataframe["macd"], dataframe["macdsignal"])
            & (dataframe["macdhist"] < 0)
            & (dataframe["close"] < dataframe["ema200"])
            & (dataframe["rsi"].between(30, 50))
            & (dataframe["adx"] > self.entry_adx_threshold)
            & (dataframe["volume"] > 0),
            ["enter_short", "enter_tag"],
        ] = (1, "macd_active_short")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            qtpylib.crossed_below(dataframe["macd"], dataframe["macdsignal"]),
            ["exit_long", "exit_tag"],
        ] = (1, "macd_active_cross_exit")
        dataframe.loc[
            qtpylib.crossed_above(dataframe["macd"], dataframe["macdsignal"]),
            ["exit_short", "exit_tag"],
        ] = (1, "macd_active_cross_exit")
        return dataframe


class ModelMacdMomentumActive24(ModelMacdMomentumActive):
    entry_adx_threshold = 24


class ModelMacdMomentumActive26(ModelMacdMomentumActive):
    entry_adx_threshold = 26


class ModelMacdMomentumActive28(ModelMacdMomentumActive):
    entry_adx_threshold = 28


class ModelMacdMomentumActive30(ModelMacdMomentumActive):
    entry_adx_threshold = 30


class ModelMacdMomentumResponsive24(ModelMacdMomentumActive):
    """Enter an established 5m impulse instead of requiring the crossover candle."""

    entry_adx_threshold = 24

    @property
    def protections(self):
        return [{"method": "CooldownPeriod", "stop_duration_candles": 6}]

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["macd"] > dataframe["macdsignal"])
            & (dataframe["macdhist"] > 0)
            & (dataframe["close"] > dataframe["ema200"])
            & (dataframe["rsi"].between(48, 72))
            & (dataframe["adx"] > self.entry_adx_threshold)
            & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "macd_responsive_long")
        dataframe.loc[
            (dataframe["macd"] < dataframe["macdsignal"])
            & (dataframe["macdhist"] < 0)
            & (dataframe["close"] < dataframe["ema200"])
            & (dataframe["rsi"].between(28, 52))
            & (dataframe["adx"] > self.entry_adx_threshold)
            & (dataframe["volume"] > 0),
            ["enter_short", "enter_tag"],
        ] = (1, "macd_responsive_short")
        return dataframe


class ModelRsi50MacdZero(_ResearchBase):
    """5m entries using RSI 50 direction and MACD histogram zero transitions."""

    timeframe = "5m"

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]
        dataframe["macdhist"] = macd["macdhist"]
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        histogram_turns_positive = (
            (dataframe["macdhist"] > 0)
            & (dataframe["macdhist"].shift(1) <= 0)
        )
        histogram_turns_negative = (
            (dataframe["macdhist"] < 0)
            & (dataframe["macdhist"].shift(1) >= 0)
        )
        dataframe.loc[
            (dataframe["rsi"] > 50)
            & histogram_turns_positive
            & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "rsi50_macd_zero_long")
        dataframe.loc[
            (dataframe["rsi"] < 50)
            & histogram_turns_negative
            & (dataframe["volume"] > 0),
            ["enter_short", "enter_tag"],
        ] = (1, "rsi50_macd_zero_short")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["macdhist"] < 0)
            & (dataframe["macdhist"].shift(1) >= 0),
            ["exit_long", "exit_tag"],
        ] = (1, "macd_zero_exit")
        dataframe.loc[
            (dataframe["macdhist"] > 0)
            & (dataframe["macdhist"].shift(1) <= 0),
            ["exit_short", "exit_tag"],
        ] = (1, "macd_zero_exit")
        return dataframe


class ModelMacdMomentumFast(_ResearchBase):
    """Highest-frequency 5m MACD candidate with broad momentum guardrails."""

    timeframe = "5m"

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        macd = ta.MACD(dataframe, fastperiod=8, slowperiod=21, signalperiod=5)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            qtpylib.crossed_above(dataframe["macd"], dataframe["macdsignal"])
            & (dataframe["rsi"].between(38, 76))
            & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "macd_fast_long")
        dataframe.loc[
            qtpylib.crossed_below(dataframe["macd"], dataframe["macdsignal"])
            & (dataframe["rsi"].between(24, 62))
            & (dataframe["volume"] > 0),
            ["enter_short", "enter_tag"],
        ] = (1, "macd_fast_short")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            qtpylib.crossed_below(dataframe["macd"], dataframe["macdsignal"]),
            ["exit_long", "exit_tag"],
        ] = (1, "macd_fast_cross_exit")
        dataframe.loc[
            qtpylib.crossed_above(dataframe["macd"], dataframe["macdsignal"]),
            ["exit_short", "exit_tag"],
        ] = (1, "macd_fast_cross_exit")
        return dataframe


class ModelSupertrendConsensus(_ResearchBase):
    """ATR Supertrend reversal confirmed by EMA and RSI regime."""

    startup_candle_count = 220

    @staticmethod
    def _supertrend(dataframe: DataFrame, period: int = 10, multiplier: float = 3.0):
        atr = ta.ATR(dataframe, timeperiod=period)
        middle = (dataframe["high"] + dataframe["low"]) / 2
        upper = (middle + multiplier * atr).copy()
        lower = (middle - multiplier * atr).copy()
        trend = np.ones(len(dataframe), dtype=np.int8)
        close = dataframe["close"].to_numpy()
        for i in range(1, len(dataframe)):
            if close[i] > upper.iat[i - 1]:
                trend[i] = 1
            elif close[i] < lower.iat[i - 1]:
                trend[i] = -1
            else:
                trend[i] = trend[i - 1]
                if trend[i] == 1 and lower.iat[i] < lower.iat[i - 1]:
                    lower.iat[i] = lower.iat[i - 1]
                if trend[i] == -1 and upper.iat[i] > upper.iat[i - 1]:
                    upper.iat[i] = upper.iat[i - 1]
        return trend

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["supertrend"] = self._supertrend(dataframe)
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        long_flip = (dataframe["supertrend"] == 1) & (dataframe["supertrend"].shift(1) == -1)
        short_flip = (dataframe["supertrend"] == -1) & (dataframe["supertrend"].shift(1) == 1)
        dataframe.loc[
            long_flip
            & (dataframe["close"] > dataframe["ema200"])
            & (dataframe["rsi"] > 50)
            & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "supertrend_long")
        dataframe.loc[
            short_flip
            & (dataframe["close"] < dataframe["ema200"])
            & (dataframe["rsi"] < 50)
            & (dataframe["volume"] > 0),
            ["enter_short", "enter_tag"],
        ] = (1, "supertrend_short")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            dataframe["supertrend"] == -1,
            ["exit_long", "exit_tag"],
        ] = (1, "supertrend_flip")
        dataframe.loc[
            dataframe["supertrend"] == 1,
            ["exit_short", "exit_tag"],
        ] = (1, "supertrend_flip")
        return dataframe
