from __future__ import annotations

import pandas as pd

from quant_a_stock.strategy.base import StrategyParameters, assert_long_only_signal


STRATEGY_NAME = "sma_trend_filter"


def generate_signals(
    candles: pd.DataFrame,
    *,
    fast_window: int = 20,
    slow_window: int = 60,
    trend_window: int = 120,
) -> pd.Series:
    frame = candles.copy()
    fast_sma = frame["close"].rolling(fast_window, min_periods=fast_window).mean()
    slow_sma = frame["close"].rolling(slow_window, min_periods=slow_window).mean()
    trend_sma = frame["close"].rolling(trend_window, min_periods=trend_window).mean()

    signal = ((fast_sma > slow_sma) & (frame["close"] > trend_sma)).astype(int)
    signal = signal.fillna(0).astype(int)
    signal.name = "signal"
    assert_long_only_signal(signal)
    return signal


class SmaTrendFilterStrategy:
    name = STRATEGY_NAME

    def generate_signals(
        self, candles: pd.DataFrame, parameters: StrategyParameters
    ) -> pd.Series:
        return generate_signals(
            candles,
            fast_window=parameters.fast_window,
            slow_window=parameters.slow_window,
            trend_window=parameters.trend_window,
        )

