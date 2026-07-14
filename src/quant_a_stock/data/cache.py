from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant_a_stock.config import DEFAULT_PATHS
from quant_a_stock.io_utils import atomic_write_csv
from quant_a_stock.io_utils import exclusive_file_lock


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
    lock_path = path.parent / ".locks" / f"{symbol}.lock"
    with exclusive_file_lock(lock_path, owner=f"daily-cache:{symbol}"):
        output = _merge_newest_cache(path, output)
        if "timestamp" in output.columns:
            output["timestamp"] = pd.to_datetime(output["timestamp"]).dt.strftime("%Y-%m-%d")
        output = output.loc[:, [column for column in CACHE_COLUMNS if column in output.columns]]
        atomic_write_csv(output, path, index=False)
    return path


def _merge_newest_cache(path: Path, incoming: pd.DataFrame) -> pd.DataFrame:
    if not path.exists() or "timestamp" not in incoming.columns:
        return incoming
    try:
        existing = pd.read_csv(path, dtype={"symbol": str})
    except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError):
        return incoming
    if existing.empty or "timestamp" not in existing.columns:
        return incoming
    old_dates = pd.to_datetime(existing["timestamp"], errors="coerce")
    new_dates = pd.to_datetime(incoming["timestamp"], errors="coerce")
    existing_is_newer = old_dates.max() > new_dates.max()
    frames = [incoming, existing] if existing_is_newer else [existing, incoming]
    merged = pd.concat(frames, ignore_index=True)
    merged["timestamp"] = pd.to_datetime(merged["timestamp"], errors="coerce")
    return merged.dropna(subset=["timestamp"]).sort_values("timestamp").drop_duplicates("timestamp", keep="last")


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
