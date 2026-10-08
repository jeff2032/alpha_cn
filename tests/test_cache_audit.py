from __future__ import annotations

import pandas as pd

from quant_a_stock.data.cache_audit import audit_daily_cache


def _write_cache(tmp_path, symbol: str, closes: list[float]) -> None:
    daily = tmp_path / "akshare" / "daily"
    daily.mkdir(parents=True, exist_ok=True)
    dates = pd.bdate_range("2026-09-01", periods=len(closes))
    raw_price = 10.0
    frame = pd.DataFrame(
        {
            "timestamp": dates,
            "open": closes,
            "high": [value * 1.02 for value in closes],
            "low": [value * 0.98 for value in closes],
            "close": closes,
            "volume": 1_000_000,
            "amount": raw_price * 1_000_000,
            "symbol": symbol,
        }
    )
    frame.to_csv(daily / f"{symbol}.csv", index=False)


def test_cache_audit_quarantines_unstable_adjusted_basis(tmp_path) -> None:
    closes = [5.0 if index % 2 == 0 else 10.0 for index in range(20)]
    _write_cache(tmp_path, "000001", closes)
    universe = pd.DataFrame({"symbol": ["000001"], "name": ["测试公司"]})

    result = audit_daily_cache(
        universe,
        target_date="2026-09-28",
        cache_dir=tmp_path,
    )

    row = result.iloc[0]
    assert bool(row["quarantined"]) is True
    assert row["quality_status"] == "CRITICAL"
    assert int(row["basis_jump_count"]) >= 8
    assert "前复权基准频繁跳变" in row["issue"]


def test_cache_audit_keeps_consistent_cache_available(tmp_path) -> None:
    closes = [10.0] * 20
    _write_cache(tmp_path, "000001", closes)
    universe = pd.DataFrame({"symbol": ["000001"], "name": ["测试公司"]})

    result = audit_daily_cache(
        universe,
        target_date="2026-09-28",
        cache_dir=tmp_path,
    )

    row = result.iloc[0]
    assert bool(row["quarantined"]) is False
    assert row["quality_status"] == "OK"
    assert row["issue"] == ""
