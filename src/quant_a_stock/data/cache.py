from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant_a_stock.config import DEFAULT_PATHS


STANDARD_COLUMNS = [
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "symbol",
]
CACHE_COLUMNS = STANDARD_COLUMNS + ["is_suspended"]


def daily_cache_path(
    symbol: str,
    *,
    source: str = "akshare",
    cache_dir: Path | None = None,
) -> Path:
    root = cache_dir or DEFAULT_PATHS.data_cache
    return root / source / "daily" / f"{symbol}.csv"


def save_daily_cache(
    candles: pd.DataFrame,
    symbol: str,
    *,
    source: str = "akshare",
    cache_dir: Path | None = None,
) -> Path:
    path = daily_cache_path(symbol, source=source, cache_dir=cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    output = candles.copy()
    if "timestamp" in output.columns:
        output["timestamp"] = pd.to_datetime(output["timestamp"]).dt.strftime("%Y-%m-%d")
    output = output.loc[:, [column for column in CACHE_COLUMNS if column in output.columns]]
    output.to_csv(path, index=False)
    return path


def load_daily_cache(
    symbol: str,
    *,
    source: str = "akshare",
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    path = daily_cache_path(symbol, source=source, cache_dir=cache_dir)
    if not path.exists():
        raise FileNotFoundError(
            f"Missing cached data for {symbol}: {path}. Run sync-daily first."
        )
    frame = pd.read_csv(path)
    if "timestamp" in frame.columns:
        frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    return frame
