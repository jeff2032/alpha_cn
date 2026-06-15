from __future__ import annotations

import numpy as np
import pandas as pd


def add_sma(candles: pd.DataFrame, window: int, column: str = "close") -> pd.DataFrame:
    frame = candles.copy()
    frame[f"sma_{window}"] = frame[column].rolling(window=window, min_periods=window).mean()
    return frame


def add_ema(candles: pd.DataFrame, window: int, column: str = "close") -> pd.DataFrame:
    frame = candles.copy()
    frame[f"ema_{window}"] = frame[column].ewm(span=window, adjust=False).mean()
    return frame


def add_rsi(candles: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    frame = candles.copy()
    delta = frame["close"].diff()
    gain = delta.clip(lower=0).rolling(window=window, min_periods=window).mean()
    loss = (-delta.clip(upper=0)).rolling(window=window, min_periods=window).mean()
    rs = gain / loss.replace(0, np.nan)
    frame[f"rsi_{window}"] = 100 - (100 / (1 + rs))
    frame[f"rsi_{window}"] = frame[f"rsi_{window}"].fillna(50)
    return frame


def add_atr(candles: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    frame = candles.copy()
    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    frame[f"atr_{window}"] = true_range.rolling(window=window, min_periods=window).mean()
    return frame


def add_rolling_volatility(candles: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    frame = candles.copy()
    returns = frame["close"].pct_change()
    frame[f"volatility_{window}"] = returns.rolling(
        window=window, min_periods=window
    ).std()
    return frame


def add_momentum(candles: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    frame = candles.copy()
    frame[f"momentum_{window}"] = frame["close"] / frame["close"].shift(window) - 1
    return frame


def add_volume_factor(candles: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    frame = candles.copy()
    avg_volume = frame["volume"].rolling(window=window, min_periods=window).mean()
    frame[f"volume_factor_{window}"] = frame["volume"] / avg_volume
    return frame


def add_basic_features(candles: pd.DataFrame) -> pd.DataFrame:
    frame = candles.copy()
    for window in (5, 10, 20, 50, 60, 120, 200):
        frame = add_sma(frame, window)
        frame = add_ema(frame, window)
    frame = add_rsi(frame)
    frame = add_atr(frame)
    frame = add_rolling_volatility(frame)
    frame = add_momentum(frame)
    frame = add_volume_factor(frame)
    return frame

