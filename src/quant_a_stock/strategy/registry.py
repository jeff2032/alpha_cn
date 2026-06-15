from __future__ import annotations

from dataclasses import dataclass
from inspect import signature
from typing import Callable

import pandas as pd

from quant_a_stock.strategy import donchian_breakout
from quant_a_stock.strategy import ema_pullback_trend
from quant_a_stock.strategy import base_breakout_setup
from quant_a_stock.strategy import rsi_reversion
from quant_a_stock.strategy import sma_trend_filter


SignalGenerator = Callable[..., pd.Series]


@dataclass(frozen=True)
class StrategySpec:
    name: str
    generator: SignalGenerator
    description: str


STRATEGIES: dict[str, StrategySpec] = {
    sma_trend_filter.STRATEGY_NAME: StrategySpec(
        name=sma_trend_filter.STRATEGY_NAME,
        generator=sma_trend_filter.generate_signals,
        description="快线 SMA 高于慢线 SMA，且价格位于长期趋势均线上方。",
    ),
    donchian_breakout.STRATEGY_NAME: StrategySpec(
        name=donchian_breakout.STRATEGY_NAME,
        generator=donchian_breakout.generate_signals,
        description="价格突破前 N 日高点，并通过长期趋势过滤。",
    ),
    base_breakout_setup.STRATEGY_NAME: StrategySpec(
        name=base_breakout_setup.STRATEGY_NAME,
        generator=base_breakout_setup.generate_signals,
        description="寻找明显加速前的早期平台突破形态。",
    ),
    rsi_reversion.STRATEGY_NAME: StrategySpec(
        name=rsi_reversion.STRATEGY_NAME,
        generator=rsi_reversion.generate_signals,
        description="长期趋势向上时，寻找 RSI 超跌反弹。",
    ),
    ema_pullback_trend.STRATEGY_NAME: StrategySpec(
        name=ema_pullback_trend.STRATEGY_NAME,
        generator=ema_pullback_trend.generate_signals,
        description="EMA 多头趋势内，寻找 RSI 回调买点。",
    ),
}


def available_strategy_names() -> list[str]:
    return sorted(STRATEGIES)


def get_strategy(name: str) -> StrategySpec:
    try:
        return STRATEGIES[name]
    except KeyError as exc:
        choices = ", ".join(available_strategy_names())
        raise ValueError(f"不支持的策略: {name}。可用策略: {choices}") from exc


def generate_strategy_signals(
    name: str,
    candles: pd.DataFrame,
    **parameters: int | float,
) -> pd.Series:
    spec = get_strategy(name)
    accepted = set(signature(spec.generator).parameters)
    accepted.discard("candles")
    filtered = {key: value for key, value in parameters.items() if key in accepted}
    return spec.generator(candles, **filtered)
