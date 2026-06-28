from __future__ import annotations

from strategies.s01_ha_rsi_vsa import HARsiVsaStrategy
from strategies.s02_ema_cross_fast import EmaCrossFastStrategy
from strategies.s03_macd_bb_squeeze import MacdBbSqueezeStrategy
from strategies.s04_order_imbalance_scalp import OrderImbalanceScalpStrategy
from strategies.s05_rsi_divergence import RsiDivergenceStrategy
from strategies.s06_funding_momentum import FundingMomentumStrategy
from strategies.s07_breakout_volume import BreakoutVolumeStrategy
from strategies.s08_mean_reversion_bb import MeanReversionBbStrategy
from strategies.s09_ichimoku_cloud import IchimokuCloudStrategy
from strategies.s10_vwap_revert import VwapRevertStrategy
from strategies.s99_adaptive_ensemble import AdaptiveEnsembleStrategy


STRATEGIES = {
    strategy.strategy_id: strategy
    for strategy in (
        HARsiVsaStrategy(), EmaCrossFastStrategy(), MacdBbSqueezeStrategy(),
        OrderImbalanceScalpStrategy(), RsiDivergenceStrategy(), FundingMomentumStrategy(),
        BreakoutVolumeStrategy(), MeanReversionBbStrategy(), IchimokuCloudStrategy(),
        VwapRevertStrategy(),
    )
}

STRATEGY_ROTATION_IDS = tuple(key for key in STRATEGIES if key != "S99")

STRATEGIES["S99"] = AdaptiveEnsembleStrategy()


def get_strategy(strategy_id: str):
    return STRATEGIES.get(strategy_id.upper())
