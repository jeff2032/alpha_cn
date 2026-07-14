from __future__ import annotations

import pandas as pd

from quant_a_stock.data.cache import load_daily_cache
from quant_a_stock.data.cache import save_daily_cache


def test_save_daily_cache_keeps_only_standard_cache_columns(tmp_path) -> None:
    cache_dir = tmp_path / "cache"
    candles = pd.DataFrame(
        [
            {
                "timestamp": "2026-06-23",
                "open": 5.0,
                "high": 5.1,
                "low": 4.9,
                "close": 5.0,
                "volume": 100,
                "amount": 500,
                "symbol": "510300",
                "is_suspended": False,
                "pct_change": -2.0,
            }
        ]
    )

    save_daily_cache(candles, "510300", cache_dir=cache_dir)
    loaded = load_daily_cache("510300", cache_dir=cache_dir)

    assert loaded.columns.tolist() == [
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "symbol",
        "is_suspended",
    ]


def test_older_writer_cannot_remove_newer_cached_dates(tmp_path) -> None:
    cache_dir = tmp_path / "cache"
    newer = pd.DataFrame(
        [
            {"timestamp": "2026-07-13", "close": 10, "symbol": "000001"},
            {"timestamp": "2026-07-14", "close": 11, "symbol": "000001"},
        ]
    )
    stale = pd.DataFrame(
        [
            {"timestamp": "2026-07-12", "close": 9, "symbol": "000001"},
            {"timestamp": "2026-07-13", "close": 9.5, "symbol": "000001"},
        ]
    )

    save_daily_cache(newer, "000001", cache_dir=cache_dir)
    save_daily_cache(stale, "000001", cache_dir=cache_dir)
    loaded = load_daily_cache("000001", cache_dir=cache_dir)

    assert loaded["timestamp"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-07-12",
        "2026-07-13",
        "2026-07-14",
    ]
    assert loaded.loc[loaded["timestamp"] == pd.Timestamp("2026-07-13"), "close"].iloc[0] == 10
