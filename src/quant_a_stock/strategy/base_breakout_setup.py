from __future__ import annotations

import pandas as pd

from quant_a_stock.strategy.base import build_stateful_long_signal


STRATEGY_NAME = "base_breakout_setup"


def generate_signals(
    candles: pd.DataFrame,
    *,
    base_window: int = 120,
    trend_window: int = 120,
    volume_window: int = 20,
    max_base_range: float = 0.65,
    proximity_pct: float = 0.05,
    volume_ratio_min: float = 1.3,
    max_ret_20: float = 0.35,
    exit_ma_window: int = 60,
) -> pd.Series:
    close = candles["close"]
    volume = candles["volume"]

    prior_high = close.shift(1).rolling(window=base_window, min_periods=base_window).max()
    prior_low = close.shift(1).rolling(window=base_window, min_periods=base_window).min()
    base_range = prior_high / prior_low - 1

    trend_ma = close.rolling(window=trend_window, min_periods=trend_window).mean()
    trend_slope = trend_ma > trend_ma.shift(20)
    volume_ratio = volume / volume.rolling(window=volume_window, min_periods=volume_window).mean()
    ret_20 = close / close.shift(20) - 1
    exit_ma = close.rolling(window=exit_ma_window, min_periods=exit_ma_window).mean()

    near_breakout = close >= prior_high * (1 - proximity_pct)
    early_not_extended = ret_20 <= max_ret_20
    entry = (
        (base_range <= max_base_range)
        & near_breakout
        & (close > trend_ma)
        & trend_slope
        & (volume_ratio >= volume_ratio_min)
        & early_not_extended
    )
    exit_ = (close < exit_ma) | (close < trend_ma)
    return build_stateful_long_signal(entry, exit_)
