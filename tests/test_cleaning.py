from __future__ import annotations

import pandas as pd

from quant_a_stock.cleaning.pipeline import clean_candles


def test_clean_candles_sorts_deduplicates_and_filters_bad_prices() -> None:
    raw = pd.DataFrame(
        {
            "timestamp": ["2024-01-03", "2024-01-02", "2024-01-02", "bad"],
            "open": [10, 9, 0, 8],
            "high": [11, 10, 10, 9],
            "low": [9, 8, 8, 7],
            "close": [10.5, 9.5, 9.2, 8.5],
            "volume": [100, 0, 200, 100],
            "amount": [1000, 0, 1800, 900],
        }
    )

    clean = clean_candles(raw, symbol="510300")

    assert clean["timestamp"].tolist() == [
        pd.Timestamp("2024-01-02"),
        pd.Timestamp("2024-01-03"),
    ]
    assert clean["symbol"].tolist() == ["510300", "510300"]
    assert bool(clean.loc[0, "is_suspended"]) is True


def test_clean_candles_normalizes_mixed_lot_and_share_volume() -> None:
    raw = pd.DataFrame(
        {
            "timestamp": ["2026-08-10", "2026-08-11"],
            "open": [10.0, 10.0],
            "high": [10.2, 10.2],
            "low": [9.8, 9.8],
            "close": [10.0, 10.0],
            "volume": [100_000, 10_000_000],
            "amount": [100_000_000, 100_000_000],
        }
    )

    clean = clean_candles(raw, symbol="000001")

    assert clean["volume"].tolist() == [10_000_000, 10_000_000]
