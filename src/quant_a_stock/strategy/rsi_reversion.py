from __future__ import annotations

import pandas as pd

from quant_a_stock.strategy.base import build_stateful_long_signal
from quant_a_stock.strategy.indicators import rsi


STRATEGY_NAME = "rsi_reversion"


def generate_signals(
    candles: pd.DataFrame,
    *,
    rsi_window: int = 14,
    rsi_entry: float = 35.0,
    rsi_exit: float = 55.0,
    trend_window: int = 120,
) -> pd.Series:
    close = candles["close"]
    trend_sma = close.rolling(window=trend_window, min_periods=trend_window).mean()
    rsi_value = rsi(close, window=rsi_window)

    entry = (rsi_value <= rsi_entry) & (close > trend_sma)
    exit_ = (rsi_value >= rsi_exit) | (close < trend_sma)
    return build_stateful_long_signal(entry, exit_)

