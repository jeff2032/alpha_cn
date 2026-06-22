from __future__ import annotations

import pandas as pd

from quant_a_stock.cli import build_parser
from quant_a_stock.cli import _add_names_from_universe
from quant_a_stock.cli import _balanced_scan_selection
from quant_a_stock.cli import _incremental_start_from_last
from quant_a_stock.config import ProjectPaths
import quant_a_stock.cli as cli_module


def test_compare_command_parses_strategy_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "compare",
            "--symbols",
            "510300",
            "159915",
            "--strategies",
            "sma_trend_filter",
            "rsi_reversion",
            "--rsi-entry",
            "40",
        ]
    )

    assert args.command == "compare"
    assert args.strategies == ["sma_trend_filter", "rsi_reversion"]
    assert args.rsi_entry == 40


def test_scan_pattern_command_parses_setup_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "scan-pattern",
            "--symbols",
            "510300",
            "--min-score",
            "60",
            "--proximity-pct",
            "0.03",
            "--stages",
            "watch",
            "near_breakout",
            "--min-amount-ma20",
            "100000000",
        ]
    )

    assert args.command == "scan-pattern"
    assert args.min_score == 60
    assert args.proximity_pct == 0.03
    assert args.stages == ["watch", "near_breakout"]
    assert args.min_amount_ma20 == 100000000


def test_scan_pattern_command_parses_accumulation_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "scan-pattern",
            "--pattern",
            "accumulation_setup",
            "--base-window",
            "250",
            "--stages",
            "accumulation",
            "--max-close-vs-trend",
            "0.12",
            "--max-ret-60",
            "0.30",
            "--max-price-position",
            "0.82",
        ]
    )

    assert args.command == "scan-pattern"
    assert args.pattern == "accumulation_setup"
    assert args.base_window == 250
    assert args.stages == ["accumulation"]
    assert args.max_ret_60 == 0.30
    assert args.max_price_position == 0.82


def test_scan_pattern_command_parses_trend_pullback_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "scan-pattern",
            "--pattern",
            "trend_pullback_setup",
            "--stages",
            "trend_pullback",
            "trend_resume",
            "--min-ret-60",
            "0.20",
            "--filter-max-ret-20",
            "0.18",
            "--max-drawdown-from-high",
            "0.30",
            "--fast-trend-window",
            "55",
        ]
    )

    assert args.command == "scan-pattern"
    assert args.pattern == "trend_pullback_setup"
    assert args.stages == ["trend_pullback", "trend_resume"]
    assert args.min_ret_60 == 0.20
    assert args.filter_max_ret_20 == 0.18
    assert args.max_drawdown_from_high == 0.30
    assert args.fast_trend_window == 55


def test_balanced_scan_selection_keeps_multiple_scan_sources() -> None:
    frame = pd.DataFrame(
        [
            {"symbol": "1", "score": 100, "scan_source": "scan_trend_pullback_setup_20260615"},
            {"symbol": "2", "score": 99, "scan_source": "scan_trend_pullback_setup_20260615"},
            {"symbol": "3", "score": 98, "scan_source": "scan_trend_pullback_setup_20260615"},
            {"symbol": "4", "score": 60, "scan_source": "scan_accumulation_setup_20260615"},
            {"symbol": "5", "score": 59, "scan_source": "scan_accumulation_setup_20260615"},
            {"symbol": "6", "score": 58, "scan_source": "scan_base_breakout_setup_20260615"},
        ]
    )

    result = _balanced_scan_selection(frame, top=3)

    assert set(result["scan_source"]) == {
        "scan_trend_pullback_setup_20260615",
        "scan_accumulation_setup_20260615",
        "scan_base_breakout_setup_20260615",
    }


def test_add_names_from_universe_fills_only_missing_names(tmp_path, monkeypatch) -> None:
    universe_path = tmp_path / "data" / "universe" / "a_stock.csv"
    universe_path.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {"symbol": "002415", "name": "海康威视", "market": "sz"},
            {"symbol": "600150", "name": "中国船舶", "market": "sh"},
        ]
    ).to_csv(universe_path, index=False)
    monkeypatch.setattr(cli_module, "DEFAULT_PATHS", ProjectPaths(root=tmp_path))
    frame = pd.DataFrame(
        [
            {"symbol": "2415", "name": ""},
            {"symbol": "600150", "name": "自有名称"},
        ]
    )

    result = _add_names_from_universe(frame)

    assert result.loc[result["symbol"] == "002415", "name"].iloc[0] == "海康威视"
    assert result.loc[result["symbol"] == "600150", "name"].iloc[0] == "自有名称"


def test_sync_stock_universe_command_parses_batch_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "sync-stock-universe",
            "--symbols",
            "688143",
            "688146",
            "--since",
            "2020-01-01",
            "--sleep",
            "1.5",
            "--workers",
            "4",
            "--limit",
            "2",
        ]
    )

    assert args.command == "sync-stock-universe"
    assert args.symbols == ["688143", "688146"]
    assert args.sleep == 1.5
    assert args.workers == 4
    assert args.limit == 2


def test_sync_stock_universe_command_parses_incremental_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "sync-stock-universe",
            "--symbols",
            "000001",
            "--incremental",
            "--lookback-days",
            "30",
            "--no-skip-existing",
        ]
    )

    assert args.command == "sync-stock-universe"
    assert args.incremental is True
    assert args.lookback_days == 30
    assert args.skip_existing is False
    assert args.workers == 1


def test_sync_daily_command_parses_incremental_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "sync-daily",
            "--symbols",
            "000001",
            "--incremental",
            "--lookback-days",
            "90",
        ]
    )

    assert args.command == "sync-daily"
    assert args.incremental is True
    assert args.lookback_days == 90


def test_incremental_start_from_last_respects_lookback_and_since() -> None:
    assert (
        _incremental_start_from_last(
            pd.Timestamp("2026-06-15"),
            since="2020-01-01",
            lookback_days=30,
        )
        == "2026-05-16"
    )
    assert (
        _incremental_start_from_last(
            pd.Timestamp("2026-06-15"),
            since="2026-06-01",
            lookback_days=30,
        )
        == "2026-06-01"
    )


def test_cache_status_command_parses_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "cache-status",
            "--universe-file",
            "data/universe/a_stock.csv",
            "--show-missing",
            "--top",
            "10",
        ]
    )

    assert args.command == "cache-status"
    assert args.universe_file == "data/universe/a_stock.csv"
    assert args.show_missing is True
    assert args.top == 10


def test_cache_date_status_command_parses_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "cache-date-status",
            "--universe-file",
            "data/universe/a_stock.csv",
            "--target-date",
            "2026-06-12",
            "--exact-target-date",
            "--show-stale",
            "--output-stale",
            "data/universe/stale.csv",
        ]
    )

    assert args.command == "cache-date-status"
    assert args.target_date == "2026-06-12"
    assert args.exact_target_date is True
    assert args.show_stale is True
    assert args.output_stale == "data/universe/stale.csv"


def test_sentiment_score_command_parses_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "sentiment-score",
            "--latest-scan",
            "--target-date",
            "2026-06-12",
            "--news-days",
            "10",
            "--top",
            "30",
        ]
    )

    assert args.command == "sentiment-score"
    assert args.latest_scan is True
    assert args.target_date == "2026-06-12"
    assert args.news_days == 10
    assert args.top == 30


def test_market_theme_command_parses_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "market-theme",
            "--target-date",
            "2026-06-12",
            "--top",
            "15",
        ]
    )

    assert args.command == "market-theme"
    assert args.target_date == "2026-06-12"
    assert args.top == 15


def test_research_candidates_command_parses_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "research-candidates",
            "--scan-report",
            "reports/scan.csv",
            "--sentiment-report",
            "reports/sentiment.csv",
            "--target-date",
            "2026-06-12",
            "--risk-days",
            "90",
            "--no-fetch-notices",
        ]
    )

    assert args.command == "research-candidates"
    assert args.scan_report == "reports/scan.csv"
    assert args.sentiment_report == "reports/sentiment.csv"
    assert args.target_date == "2026-06-12"
    assert args.risk_days == 90
    assert args.fetch_notices is False


def test_research_backtest_command_parses_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "research-backtest",
            "--since",
            "2024-06-12",
            "--until",
            "2026-06-12",
            "--top-n",
            "5",
            "--rebalance-frequency",
            "W",
            "--limit",
            "100",
        ]
    )

    assert args.command == "research-backtest"
    assert args.since == "2024-06-12"
    assert args.until == "2026-06-12"
    assert args.top_n == 5
    assert args.rebalance_frequency == "W"
    assert args.limit == 100


def test_research_optimize_command_parses_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "research-optimize",
            "--top-ns",
            "5,10",
            "--min-scores",
            "45,50",
            "--max-ret-20s",
            "0.15,0.25",
            "--rebalance-frequencies",
            "W",
            "M",
            "--display-top",
            "5",
        ]
    )

    assert args.command == "research-optimize"
    assert args.top_ns == "5,10"
    assert args.min_scores == "45,50"
    assert args.max_ret_20s == "0.15,0.25"
    assert args.rebalance_frequencies == ["W", "M"]
    assert args.display_top == 5


def test_snapshot_research_command_parses_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "snapshot-research",
            "--target-date",
            "2026-06-12",
            "--scan-report",
            "reports/scan.csv",
        ]
    )

    assert args.command == "snapshot-research"
    assert args.target_date == "2026-06-12"
    assert args.scan_report == "reports/scan.csv"


def test_daily_research_summary_command_parses_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "daily-research-summary",
            "--target-date",
            "2026-06-12",
            "--top",
            "20",
        ]
    )

    assert args.command == "daily-research-summary"
    assert args.target_date == "2026-06-12"
    assert args.top == 20


def test_research_review_command_parses_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "research-review",
            "--since",
            "2026-06-12",
            "--until",
            "2026-06-18",
            "--top-movers",
            "10",
            "--universe-file",
            "data/universe/a_stock.csv",
        ]
    )

    assert args.command == "research-review"
    assert args.since == "2026-06-12"
    assert args.until == "2026-06-18"
    assert args.top_movers == 10
    assert args.universe_file == "data/universe/a_stock.csv"


def test_warehouse_ingest_command_parses_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "warehouse-ingest",
            "--target-date",
            "2026-06-18",
            "--reports-dir",
            "reports",
            "--warehouse-dir",
            "data/warehouse",
            "--run-id",
            "test-run",
        ]
    )

    assert args.command == "warehouse-ingest"
    assert args.target_date == "2026-06-18"
    assert args.reports_dir == "reports"
    assert args.warehouse_dir == "data/warehouse"
    assert args.run_id == "test-run"


def test_warehouse_status_command_parses_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(["warehouse-status", "--warehouse-dir", "data/warehouse"])

    assert args.command == "warehouse-status"
    assert args.warehouse_dir == "data/warehouse"


def test_warehouse_review_command_parses_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "warehouse-review",
            "--since",
            "2026-06-12",
            "--until",
            "2026-06-18",
            "--warehouse-dir",
            "data/warehouse",
        ]
    )

    assert args.command == "warehouse-review"
    assert args.since == "2026-06-12"
    assert args.until == "2026-06-18"
    assert args.warehouse_dir == "data/warehouse"


def test_warehouse_backfill_snapshots_command_parses_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "warehouse-backfill-snapshots",
            "--since",
            "2026-06-12",
            "--until",
            "2026-06-18",
            "--snapshot-root",
            "data/snapshots/research",
            "--display-top",
            "5",
        ]
    )

    assert args.command == "warehouse-backfill-snapshots"
    assert args.since == "2026-06-12"
    assert args.until == "2026-06-18"
    assert args.snapshot_root == "data/snapshots/research"
    assert args.display_top == 5


def test_warehouse_sync_universe_command_parses_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "warehouse-sync-universe",
            "--universe-file",
            "data/universe/a_stock.csv",
            "--target-date",
            "2026-06-18",
        ]
    )

    assert args.command == "warehouse-sync-universe"
    assert args.universe_file == "data/universe/a_stock.csv"
    assert args.target_date == "2026-06-18"


def test_warehouse_sync_candles_command_parses_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "warehouse-sync-candles",
            "--symbols",
            "000001",
            "600999",
            "--since",
            "2020-01-01",
            "--target-date",
            "2026-06-18",
            "--limit",
            "2",
            "--force",
        ]
    )

    assert args.command == "warehouse-sync-candles"
    assert args.symbols == ["000001", "600999"]
    assert args.since == "2020-01-01"
    assert args.target_date == "2026-06-18"
    assert args.limit == 2
    assert args.force is True
