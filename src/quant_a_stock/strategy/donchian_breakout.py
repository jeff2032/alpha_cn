from __future__ import annotations

import pandas as pd

from quant_a_stock.strategy.base import build_stateful_long_signal


STRATEGY_NAME = "donchian_breakout"


def generate_signals(
    candles: pd.DataFrame,
    *,
    breakout_window: int = 55,
    exit_window: int = 20,
    trend_window: int = 120,
) -> pd.Series:
    close = candles["close"]
    previous_high = close.shift(1).rolling(
        window=breakout_window, min_periods=breakout_window
    ).max()
    previous_low = close.shift(1).rolling(window=exit_window, min_periods=exit_window).min()
    trend_sma = close.rolling(window=trend_window, min_periods=trend_window).mean()

    entry = (close > previous_high) & (close > trend_sma)
    exit_ = (close < previous_low) | (close < trend_sma)
    return build_stateful_long_signal(entry, exit_)

