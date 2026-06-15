from __future__ import annotations

import pandas as pd

from quant_a_stock.strategy.base import build_stateful_long_signal
from quant_a_stock.strategy.indicators import rsi


STRATEGY_NAME = "ema_pullback_trend"


def generate_signals(
    candles: pd.DataFrame,
    *,
    ema_fast_window: int = 20,
    ema_slow_window: int = 60,
    trend_window: int = 120,
    rsi_window: int = 14,
    rsi_entry: float = 45.0,
    rsi_exit: float = 60.0,
) -> pd.Series:
    close = candles["close"]
    ema_fast = close.ewm(span=ema_fast_window, adjust=False).mean()
    ema_slow = close.ewm(span=ema_slow_window, adjust=False).mean()
    trend_sma = close.rolling(window=trend_window, min_periods=trend_window).mean()
    rsi_value = rsi(close, window=rsi_window)

    uptrend = (close > trend_sma) & (ema_fast > ema_slow)
    entry = uptrend & (rsi_value <= rsi_entry)
    exit_ = (rsi_value >= rsi_exit) | (close < trend_sma) | (ema_fast < ema_slow)
    return build_stateful_long_signal(entry, exit_)

