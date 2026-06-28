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
from strategies.market_router import ChartAdaptiveRouterStrategy, build_catalog_strategies


LEGACY_STRATEGIES = {
    strategy.strategy_id: strategy
    for strategy in (
        HARsiVsaStrategy(), EmaCrossFastStrategy(), MacdBbSqueezeStrategy(),
        OrderImbalanceScalpStrategy(), RsiDivergenceStrategy(), FundingMomentumStrategy(),
        BreakoutVolumeStrategy(), MeanReversionBbStrategy(), IchimokuCloudStrategy(),
        VwapRevertStrategy(),
    )
}

CATALOG_STRATEGIES = build_catalog_strategies()

STRATEGIES = {
    **LEGACY_STRATEGIES,
    **{strategy.strategy_id: strategy for strategy in CATALOG_STRATEGIES},
}

STRATEGIES["S99"] = ChartAdaptiveRouterStrategy(CATALOG_STRATEGIES)

STRATEGY_ROTATION_IDS = ("S99",)


def get_strategy(strategy_id: str):
    return STRATEGIES.get(strategy_id.upper())
