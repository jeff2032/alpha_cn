from __future__ import annotations

import pandas as pd

from quant_a_stock.data.calendar import cached_trading_dates
from quant_a_stock.data.calendar import latest_cached_trading_date_on_or_before
from quant_a_stock.data.calendar import load_official_trading_dates
from quant_a_stock.data.calendar import resolve_official_trading_date
from quant_a_stock.data.calendar import resolve_cached_trading_date


def test_resolve_cached_trading_date_skips_exchange_holiday(tmp_path) -> None:
    daily_dir = tmp_path / "akshare" / "daily"
    daily_dir.mkdir(parents=True)
    for symbol in ("000001", "000002"):
        pd.DataFrame(
            [
                {"timestamp": "2026-06-17", "close": 10, "symbol": symbol},
                {"timestamp": "2026-06-18", "close": 11, "symbol": symbol},
            ]
        ).to_csv(daily_dir / f"{symbol}.csv", index=False)

    dates = cached_trading_dates(cache_dir=tmp_path, min_count=2)

    assert [item.date().isoformat() for item in dates] == ["2026-06-17", "2026-06-18"]
    assert latest_cached_trading_date_on_or_before(
        "2026-06-19",
        cache_dir=tmp_path,
        min_count=2,
    ).date().isoformat() == "2026-06-18"
    assert resolve_cached_trading_date(
        "2026-06-19",
        cache_dir=tmp_path,
        min_count=2,
    ).date().isoformat() == "2026-06-18"


def test_official_calendar_resolves_weekday_holiday(tmp_path) -> None:
    path = tmp_path / "calendar.csv"
    pd.DataFrame(
        {"trade_date": ["2026-09-30", "2026-10-08", "2026-10-09"]}
    ).to_csv(path, index=False)

    dates = load_official_trading_dates(path=path)
    resolved, source, error = resolve_official_trading_date(
        "2026-10-07",
        path=path,
    )

    assert [item.date().isoformat() for item in dates] == [
        "2026-09-30",
        "2026-10-08",
        "2026-10-09",
    ]
    assert resolved.date().isoformat() == "2026-09-30"
    assert source == "official_calendar"
    assert error == ""
