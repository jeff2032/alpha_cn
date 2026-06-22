from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant_a_stock.config import DEFAULT_PATHS


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


def cached_trading_dates(*, cache_dir: Path | None = None, min_count: int = 100) -> list[pd.Timestamp]:
    """Infer real trading dates from local daily cache coverage.

    This avoids treating exchange holidays as stale data days. A date is accepted
    only when it appears in at least ``min_count`` cached symbols.
    """

    root = cache_dir or DEFAULT_PATHS.data_cache
    daily_dir = root / "akshare" / "daily"
    if not daily_dir.exists():
        return []

    counts: dict[str, int] = {}
    for path in daily_dir.glob("*.csv"):
        try:
            timestamps = pd.read_csv(path, usecols=["timestamp"])["timestamp"]
        except Exception:
            continue
        dates = pd.to_datetime(timestamps, errors="coerce").dropna().dt.date.astype(str).unique()
        for date in dates:
            counts[str(date)] = counts.get(str(date), 0) + 1

    return [
        pd.Timestamp(date).normalize()
        for date, count in sorted(counts.items())
        if count >= min_count
    ]


def latest_cached_trading_date_on_or_before(
    date: str | pd.Timestamp,
    *,
    cache_dir: Path | None = None,
    min_count: int = 100,
) -> pd.Timestamp | None:
    target = pd.Timestamp(date).normalize()
    eligible = [
        trading_date
        for trading_date in cached_trading_dates(cache_dir=cache_dir, min_count=min_count)
        if trading_date <= target
    ]
    return eligible[-1] if eligible else None


def resolve_cached_trading_date(
    value: str | pd.Timestamp | None = None,
    *,
    cache_dir: Path | None = None,
    min_count: int = 100,
) -> pd.Timestamp:
    """Resolve a requested date to the latest cached A-share trading date."""

    target = pd.Timestamp(value).normalize() if value else pd.Timestamp.now().normalize()
    latest = latest_cached_trading_date_on_or_before(
        target,
        cache_dir=cache_dir,
        min_count=min_count,
    )
    if latest is not None:
        return latest

    while target.weekday() >= 5:
        target -= pd.Timedelta(days=1)
    return target
