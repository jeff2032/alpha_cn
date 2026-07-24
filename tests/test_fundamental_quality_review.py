from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant_a_stock.research.fundamental_quality_review import evaluate_fundamental_quality_history


def _write_candles(path: Path, closes: list[float]) -> None:
    dates = pd.bdate_range("2026-07-01", periods=len(closes))
    pd.DataFrame(
        {
            "timestamp": dates,
            "open": closes,
            "close": closes,
        }
    ).to_csv(path, index=False)


def test_quality_review_uses_next_open_and_groups_outcomes(tmp_path: Path) -> None:
    _write_candles(tmp_path / "000001.csv", [10, 10, 11, 12, 13, 14, 15])
    _write_candles(tmp_path / "000002.csv", [10, 10, 9, 8, 7, 6, 5])
    _write_candles(tmp_path / "510300.csv", [10, 10, 10, 10, 10, 10, 10])
    history = pd.DataFrame(
        [
            {
                "target_date": "2026-07-01",
                "symbol": "000001",
                "name": "通过样本",
                "quality_verdict": "pass",
            },
            {
                "target_date": "2026-07-01",
                "symbol": "000002",
                "name": "否决样本",
                "quality_verdict": "reject",
            },
        ]
    )

    details, summary = evaluate_fundamental_quality_history(
        history,
        cache_root=tmp_path,
        horizons=(3, 5),
    )

    passed = details[details["symbol"] == "000001"].iloc[0]
    rejected = details[details["symbol"] == "000002"].iloc[0]
    assert passed["entry_date"] == "2026-07-02"
    assert passed["return_3d_pct"] == 20.0
    assert rejected["return_3d_pct"] == -20.0
    assert set(summary["quality_group"]) == {"通过", "否决"}
