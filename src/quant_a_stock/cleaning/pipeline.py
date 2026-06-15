from __future__ import annotations

import pandas as pd

from quant_a_stock.data.cache import STANDARD_COLUMNS


PRICE_COLUMNS = ["open", "high", "low", "close"]
NUMERIC_COLUMNS = PRICE_COLUMNS + ["volume", "amount"]


def clean_candles(
    candles: pd.DataFrame,
    *,
    symbol: str | None = None,
    keep_suspension_flag: bool = True,
) -> pd.DataFrame:
    """Normalize, sort, deduplicate, and filter daily OHLCV candles."""

    if candles.empty:
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    missing = {"timestamp", "open", "high", "low", "close"} - set(candles.columns)
    if missing:
        raise ValueError(f"Missing required candle columns: {sorted(missing)}")

    frame = candles.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    frame = frame.dropna(subset=["timestamp"])

    for column in NUMERIC_COLUMNS:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        else:
            frame[column] = 0.0

    if "symbol" not in frame.columns:
        frame["symbol"] = symbol or ""
    if symbol is not None:
        frame["symbol"] = symbol

    frame = frame.dropna(subset=PRICE_COLUMNS)
    for column in PRICE_COLUMNS:
        frame = frame[frame[column] > 0]

    frame = frame.sort_values("timestamp")
    frame = frame.drop_duplicates(subset=["timestamp", "symbol"], keep="last")

    if keep_suspension_flag:
        frame["is_suspended"] = frame["volume"].fillna(0) <= 0

    ordered = STANDARD_COLUMNS + [
        column for column in frame.columns if column not in STANDARD_COLUMNS
    ]
    return frame.loc[:, ordered].reset_index(drop=True)

