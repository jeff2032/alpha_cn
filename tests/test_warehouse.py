from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant_a_stock.warehouse import backfill_research_snapshots
from quant_a_stock.warehouse import ingest_latest_reports
from quant_a_stock.warehouse import sync_daily_candles_to_warehouse
from quant_a_stock.warehouse import sync_stock_universe_to_warehouse
from quant_a_stock.warehouse import warehouse_review
from quant_a_stock.warehouse import warehouse_status


def _write_csv(path: Path, rows: list[dict]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False)


def test_ingest_latest_reports_builds_parquet_and_review_views(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    warehouse_dir = tmp_path / "warehouse"

    _write_csv(
        reports_dir / "research_candidates_20260618_070000.csv",
        [
            {
                "symbol": "2137",
                "name": "实益达",
                "research_tier": "A2",
                "research_score": 72.5,
            }
        ],
    )
    _write_csv(
        reports_dir / "daily_research_candidates_20260618_070000.csv",
        [{"symbol": "600999", "name": "招商证券", "research_tier": "A3"}],
    )
    _write_csv(
        reports_dir / "sentiment_watchlist_20260618_070000.csv",
        [{"symbol": "002137", "sentiment_score": 66.0}],
    )
    _write_csv(
        reports_dir / "market_theme_20260618_070000.csv",
        [{"theme": "半导体", "theme_score": 80.0}],
    )
    _write_csv(
        reports_dir / "research_review_details_20260618_070000.csv",
        [
            {
                "signal_date": "2026-06-17",
                "next_date": "2026-06-18",
                "symbol": "002137",
                "tier": "A2",
                "next_ret": 0.10,
                "ret_3d": 0.15,
            },
            {
                "signal_date": "2026-06-17",
                "next_date": "2026-06-18",
                "symbol": "600999",
                "tier": "A3",
                "next_ret": -0.02,
                "ret_3d": 0.01,
            },
        ],
    )
    _write_csv(
        reports_dir / "research_review_summary_20260618_070000.csv",
        [{"table": "by_tier", "tier": "A2", "count": 1}],
    )
    _write_csv(
        reports_dir / "research_review_missed_20260618_070000.csv",
        [
            {
                "signal_date": "2026-06-17",
                "next_date": "2026-06-18",
                "symbol": "300001",
                "name": "特锐德",
                "next_ret": 0.20,
                "risk_level": "中",
                "miss_reason": "主线突发补票",
            }
        ],
    )
    (reports_dir / "daily_research_summary_20260618_070000.md").write_text("# 每日复盘", encoding="utf-8")

    result = ingest_latest_reports(
        target_date="2026-06-18",
        reports_dir=reports_dir,
        warehouse_dir=warehouse_dir,
        run_id="test-run",
    )

    assert result.db_path.exists()
    assert (result.parquet_root / "research_candidates" / "target_date=2026-06-18" / "test-run.parquet").exists()
    assert set(result.ingested["status"]) >= {"ingested", "indexed"}

    status = warehouse_status(warehouse_dir=warehouse_dir)
    candidates_rows = status.loc[status["table"] == "research_candidates", "rows"].iloc[0]
    missed_rows = status.loc[status["table"] == "missed_opportunities", "rows"].iloc[0]
    assert candidates_rows == 1
    assert missed_rows == 1

    review = warehouse_review(since="2026-06-17", until="2026-06-18", warehouse_dir=warehouse_dir)
    tier = review["tier"]
    miss_risk = review["miss_risk"]

    assert tier.loc[tier["tier"] == "A2", "count"].iloc[0] == 1
    assert tier.loc[tier["tier"] == "A2", "count_3d"].iloc[0] == 1
    assert tier.loc[tier["tier"] == "A2", "win_rate_1d"].iloc[0] == 1.0
    assert tier.loc[tier["tier"] == "A2", "win_rate_3d"].iloc[0] == 1.0
    assert miss_risk.loc[miss_risk["risk_level"] == "中", "count"].iloc[0] == 1

    ingest_latest_reports(
        target_date="2026-06-18",
        reports_dir=reports_dir,
        warehouse_dir=warehouse_dir,
        run_id="test-run-2",
    )
    status_after_rerun = warehouse_status(warehouse_dir=warehouse_dir)
    candidates_rows_after_rerun = status_after_rerun.loc[
        status_after_rerun["table"] == "research_candidates", "rows"
    ].iloc[0]
    assert candidates_rows_after_rerun == 1


def test_backfill_snapshots_syncs_research_snapshot_tables(tmp_path: Path) -> None:
    snapshot_root = tmp_path / "snapshots"
    day_dir = snapshot_root / "2026-06-18"
    day_dir.mkdir(parents=True)
    warehouse_dir = tmp_path / "warehouse"

    _write_csv(day_dir / "research_candidates.csv", [{"symbol": "2137", "research_tier": "A2"}])
    _write_csv(day_dir / "sentiment_watchlist.csv", [{"symbol": "002137", "sentiment_score": 66.0}])
    _write_csv(day_dir / "market_theme.csv", [{"theme": "半导体", "theme_score": 80.0}])
    _write_csv(day_dir / "scan_accumulation_setup.csv", [{"symbol": "002137", "score": 70.0}])

    result = backfill_research_snapshots(
        snapshot_root=snapshot_root,
        warehouse_dir=warehouse_dir,
        since="2026-06-18",
        until="2026-06-18",
        run_id="snapshot-test",
    )

    assert not result.ingested.empty
    status = warehouse_status(warehouse_dir=warehouse_dir)
    snapshot_rows = status.loc[status["table"] == "snapshot_research_candidates", "rows"].iloc[0]
    index_rows = status.loc[status["table"] == "snapshot_index", "rows"].iloc[0]
    assert snapshot_rows == 1
    assert index_rows == 6


def test_sync_universe_and_daily_candles_to_warehouse(tmp_path: Path) -> None:
    warehouse_dir = tmp_path / "warehouse"
    universe_file = tmp_path / "a_stock.csv"
    cache_root = tmp_path / "cache"
    daily_root = cache_root / "akshare" / "daily"
    daily_root.mkdir(parents=True)

    _write_csv(universe_file, [{"symbol": "1", "name": "平安银行", "market": "sz"}])
    _write_csv(
        daily_root / "000001.csv",
        [
            {
                "timestamp": "2026-06-17",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10.5,
                "volume": 100,
                "amount": 1000,
                "symbol": "000001",
            },
            {
                "timestamp": "2026-06-18",
                "open": 10.5,
                "high": 11.5,
                "low": 10,
                "close": 11,
                "volume": 120,
                "amount": 1300,
                "symbol": "000001",
            },
        ],
    )

    universe_result = sync_stock_universe_to_warehouse(
        universe_file=universe_file,
        target_date="2026-06-18",
        warehouse_dir=warehouse_dir,
        run_id="universe-test",
    )
    assert universe_result.ingested["row_count"].iloc[0] == 1

    candles_result = sync_daily_candles_to_warehouse(
        universe_file=universe_file,
        cache_dir=cache_root,
        target_date="2026-06-18",
        warehouse_dir=warehouse_dir,
        run_id="candles-test",
    )
    assert candles_result.ingested.loc[candles_result.ingested["symbol"] == "000001", "status"].iloc[0] == "synced"

    skipped_result = sync_daily_candles_to_warehouse(
        universe_file=universe_file,
        cache_dir=cache_root,
        target_date="2026-06-18",
        warehouse_dir=warehouse_dir,
        run_id="candles-test-2",
    )
    assert skipped_result.ingested.loc[skipped_result.ingested["symbol"] == "000001", "status"].iloc[0] == "skipped"

    status = warehouse_status(warehouse_dir=warehouse_dir)
    universe_rows = status.loc[status["table"] == "stock_universe", "rows"].iloc[0]
    candle_rows = status.loc[status["table"] == "daily_candles", "rows"].iloc[0]
    candle_symbols = status.loc[status["table"] == "daily_candles", "symbols"].iloc[0]
    assert universe_rows == 1
    assert candle_rows == 2
    assert candle_symbols == 1
