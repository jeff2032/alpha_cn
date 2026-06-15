from __future__ import annotations

import pandas as pd


def infer_missing_sessions(candles: pd.DataFrame) -> pd.DatetimeIndex:
    """Return weekday dates that are absent between the first and last candle.

    This is a lightweight placeholder until a full exchange calendar is added.
    It is useful for spotting long suspensions or provider gaps without filling
    missing rows into the backtest.
    """

    if candles.empty:
        return pd.DatetimeIndex([])
    dates = pd.to_datetime(candles["timestamp"]).dt.normalize()
    expected = pd.date_range(dates.min(), dates.max(), freq="B")
    return expected.difference(pd.DatetimeIndex(dates))

