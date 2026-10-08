from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant_a_stock.config import DEFAULT_PATHS
from quant_a_stock.io_utils import atomic_write_csv


def official_calendar_path() -> Path:
    return DEFAULT_PATHS.root / "data" / "reference" / "a_share_trading_calendar.csv"


def load_official_trading_dates(*, path: Path | None = None) -> list[pd.Timestamp]:
    calendar_path = path or official_calendar_path()
    if not calendar_path.exists():
        return []
    try:
        frame = pd.read_csv(calendar_path)
    except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError):
        return []
    column = "trade_date" if "trade_date" in frame.columns else frame.columns[0]
    values = pd.to_datetime(frame[column], errors="coerce").dropna().dt.normalize().unique()
    return sorted(pd.Timestamp(value).normalize() for value in values)


def refresh_official_trading_calendar(*, path: Path | None = None) -> list[pd.Timestamp]:
    import akshare as ak

    frame = ak.tool_trade_date_hist_sina()
    if frame.empty:
        raise RuntimeError("交易日历数据源返回空结果")
    column = "trade_date" if "trade_date" in frame.columns else frame.columns[0]
    dates = pd.to_datetime(frame[column], errors="coerce").dropna().dt.normalize()
    if dates.empty:
        raise RuntimeError("交易日历数据源没有可解析日期")
    output = pd.DataFrame({"trade_date": dates.dt.date.astype(str).drop_duplicates().sort_values()})
    calendar_path = path or official_calendar_path()
    calendar_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_csv(output, calendar_path, index=False)
    return [pd.Timestamp(value).normalize() for value in output["trade_date"]]


def resolve_official_trading_date(
    value: str | pd.Timestamp,
    *,
    path: Path | None = None,
    refresh: bool = False,
) -> tuple[pd.Timestamp, str, str]:
    """Resolve a date with the exchange calendar and return date, source, error."""

    target = pd.Timestamp(value).normalize()
    dates = load_official_trading_dates(path=path)
    error = ""
    calendar_covers_target = bool(dates and dates[-1].year >= target.year)
    if refresh or not calendar_covers_target:
        try:
            dates = refresh_official_trading_calendar(path=path)
            calendar_covers_target = bool(dates and dates[-1].year >= target.year)
        except Exception as exc:  # pragma: no cover - depends on network/provider state
            error = f"{type(exc).__name__}: {exc}"
    if calendar_covers_target:
        eligible = [date for date in dates if date <= target]
        if eligible:
            return eligible[-1], "official_calendar", error

    fallback = target
    while fallback.weekday() >= 5:
        fallback -= pd.Timedelta(days=1)
    return fallback, "weekday_fallback", error


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
