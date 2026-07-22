from __future__ import annotations

import pandas as pd

from quant_a_stock.cli import _filter_exact_cross_section
from quant_a_stock.cli import build_parser
from quant_a_stock.cli import _align_adjusted_cache_basis
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


def test_warehouse_ingest_accepts_parameters_file() -> None:
    parser = build_parser()

    args = parser.parse_args(
        ["warehouse-ingest", "--target-date", "2026-07-22", "--parameters-file", "run.json"]
    )

    assert args.parameters_file == "run.json"
    assert args.parameters_json is None


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


def test_filter_exact_cross_section_excludes_stale_symbol() -> None:
    current = pd.DataFrame(
        {"timestamp": pd.to_datetime(["2026-07-21", "2026-07-22"]), "close": [10, 11]}
    )
    stale = pd.DataFrame(
        {"timestamp": pd.to_datetime(["2025-08-11", "2025-08-12"]), "close": [5, 5.1]}
    )

    eligible, stale_symbols = _filter_exact_cross_section(
        {"000001": current, "601989": stale},
        target_date="2026-07-22",
    )

    assert list(eligible) == ["000001"]
    assert stale_symbols == ["601989"]


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
            "--max-consecutive-failures",
            "10",
            "--no-skip-existing",
        ]
    )

    assert args.command == "sync-stock-universe"
    assert args.incremental is True
    assert args.lookback_days == 30
    assert args.max_consecutive_failures == 10
    assert args.skip_existing is False
    assert args.workers == 1


def test_refresh_stock_universe_command_parses_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "refresh-stock-universe",
            "--providers",
            "exchange",
            "sina",
            "--existing-file",
            "data/universe/a_stock.csv",
            "--manual-files",
            "config/required_symbols.csv",
            "data/manual/focus_symbols.csv",
            "--output",
            "data/universe/a_stock.csv",
        ]
    )

    assert args.command == "refresh-stock-universe"
    assert args.providers == ["exchange", "sina"]
    assert args.manual_files == ["config/required_symbols.csv", "data/manual/focus_symbols.csv"]
    assert args.output == "data/universe/a_stock.csv"


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


def test_external_data_commands_parse_arguments() -> None:
    parser = build_parser()

    risk = parser.parse_args(
        [
            "risk-events",
            "--latest-scan",
            "--target-date",
            "2026-07-08",
            "--days",
            "120",
            "--top",
            "80",
        ]
    )
    flow = parser.parse_args(
        [
            "money-flow",
            "--symbols",
            "002137",
            "600999",
            "--target-date",
            "2026-07-08",
            "--lookback-days",
            "15",
            "--retries",
            "3",
            "--retry-wait",
            "2",
            "--sleep",
            "0.5",
            "--min-success-rate",
            "0.6",
            "--soft-fail",
        ]
    )
    iwencai = parser.parse_args(
        [
            "import-iwencai",
            "--file",
            "exports/iwencai.csv",
            "--target-date",
            "2026-07-08",
            "--query",
            "低位放量 半导体",
        ]
    )
    research = parser.parse_args(
        [
            "research-candidates",
            "--risk-events-report",
            "reports/risk_events.csv",
            "--money-flow-report",
            "reports/money_flow.csv",
            "--iwencai-report",
            "reports/iwencai.csv",
        ]
    )

    assert risk.command == "risk-events"
    assert risk.days == 120
    assert flow.command == "money-flow"
    assert flow.lookback_days == 15
    assert flow.retries == 3
    assert flow.retry_wait == 2
    assert flow.sleep == 0.5
    assert flow.min_success_rate == 0.6
    assert flow.soft_fail is True
    assert iwencai.command == "import-iwencai"
    assert iwencai.query == "低位放量 半导体"
    assert research.risk_events_report == "reports/risk_events.csv"
    assert research.money_flow_report == "reports/money_flow.csv"
    assert research.iwencai_report == "reports/iwencai.csv"


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


def test_adjusted_incremental_cache_aligns_old_price_basis() -> None:
    cached = pd.DataFrame(
        [
            {"timestamp": "2026-01-01", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100},
            {"timestamp": "2026-01-02", "open": 20, "high": 22, "low": 18, "close": 20, "volume": 200},
            {"timestamp": "2026-01-03", "open": 30, "high": 33, "low": 27, "close": 30, "volume": 300},
        ]
    )
    downloaded = pd.DataFrame(
        [
            {"timestamp": "2026-01-01", "close": 5},
            {"timestamp": "2026-01-02", "close": 10},
            {"timestamp": "2026-01-03", "close": 15},
        ]
    )

    aligned = _align_adjusted_cache_basis(cached, downloaded, adjust="qfq")

    assert aligned["close"].tolist() == [5.0, 10.0, 15.0]
    assert aligned["open"].tolist() == [5.0, 10.0, 15.0]
    assert aligned["volume"].tolist() == [100, 200, 300]


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


def test_cache_date_status_symbols_keeps_etf_codes(tmp_path, monkeypatch, capsys) -> None:
    daily_dir = tmp_path / "data" / "cache" / "akshare" / "daily"
    daily_dir.mkdir(parents=True)
    pd.DataFrame(
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
            }
        ]
    ).to_csv(daily_dir / "510300.csv", index=False)
    monkeypatch.setattr(cli_module, "DEFAULT_PATHS", ProjectPaths(root=tmp_path))

    parser = build_parser()
    args = parser.parse_args(
        [
            "cache-date-status",
            "--symbols",
            "510300",
            "--target-date",
            "2026-06-23",
            "--exact-target-date",
        ]
    )
    args.func(args)

    output = capsys.readouterr().out
    assert "总数: 1" in output
    assert "已到目标日期: 1" in output


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


def test_decision_signals_command_parses_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "decision-signals",
            "--target-date",
            "2026-07-08",
            "--plan-date",
            "2026-07-09",
            "--top",
            "60",
            "--display-top",
            "15",
        ]
    )

    assert args.command == "decision-signals"
    assert args.target_date == "2026-07-08"
    assert args.plan_date == "2026-07-09"
    assert args.top == 60
    assert args.display_top == 15


def test_fundamental_watchlist_command_parses_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "fundamental-watchlist",
            "--target-date",
            "2026-07-08",
            "--plan-date",
            "2026-07-09",
            "--decision-signal-report",
            "reports/decision_signals.csv",
            "--signal-top",
            "60",
            "--top",
            "12",
            "--display-top",
            "8",
        ]
    )

    assert args.command == "fundamental-watchlist"
    assert args.target_date == "2026-07-08"
    assert args.plan_date == "2026-07-09"
    assert args.decision_signal_report == "reports/decision_signals.csv"
    assert args.signal_top == 60
    assert args.top == 12
    assert args.display_top == 8


def test_research_pipeline_command_parses_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "research-pipeline",
            "--target-date",
            "2026-07-08",
            "--plan-date",
            "2026-07-09",
            "--top",
            "20",
            "--signal-top",
            "50",
            "--fundamental-top",
            "12",
            "--write-warehouse",
        ]
    )

    assert args.command == "research-pipeline"
    assert args.target_date == "2026-07-08"
    assert args.plan_date == "2026-07-09"
    assert args.top == 20
    assert args.signal_top == 50
    assert args.fundamental_top == 12
    assert args.write_warehouse is True


def test_export_context_pack_command_parses_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "export-context-pack",
            "--target-date",
            "2026-07-08",
            "--plan-date",
            "2026-07-09",
            "--top",
            "25",
            "--output-root",
            "data/context/research",
        ]
    )

    assert args.command == "export-context-pack"
    assert args.target_date == "2026-07-08"
    assert args.plan_date == "2026-07-09"
    assert args.top == 25
    assert args.output_root == "data/context/research"


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


def test_track_candidates_command_parses_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "track-candidates",
            "--since",
            "2026-06-12",
            "--until",
            "2026-06-24",
            "--snapshot-root",
            "data/snapshots/research",
            "--cache-dir",
            "data/cache",
            "--universe-file",
            "data/universe/a_stock.csv",
            "--warehouse-dir",
            "data/warehouse",
            "--gap-trade-days",
            "2",
            "--no-write-warehouse",
        ]
    )

    assert args.command == "track-candidates"
    assert args.since == "2026-06-12"
    assert args.until == "2026-06-24"
    assert args.snapshot_root == "data/snapshots/research"
    assert args.cache_dir == "data/cache"
    assert args.universe_file == "data/universe/a_stock.csv"
    assert args.warehouse_dir == "data/warehouse"
    assert args.gap_trade_days == 2
    assert args.write_warehouse is False


def test_warehouse_ingest_command_parses_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "warehouse-ingest",
            "--target-date",
            "2026-06-18",
            "--plan-date",
            "2026-06-19",
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
    assert args.plan_date == "2026-06-19"
    assert args.reports_dir == "reports"
    assert args.warehouse_dir == "data/warehouse"
    assert args.run_id == "test-run"


def test_warehouse_status_command_parses_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(["warehouse-status", "--warehouse-dir", "data/warehouse"])

    assert args.command == "warehouse-status"
    assert args.warehouse_dir == "data/warehouse"


def test_warehouse_query_command_parses_arguments() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "warehouse-query",
            "--table",
            "research_candidate_daily",
            "--columns",
            "target_date,symbol,name",
            "--since",
            "2026-06-12",
            "--until",
            "2026-06-18",
            "--limit",
            "20",
            "--warehouse-dir",
            "data/warehouse",
        ]
    )

    assert args.command == "warehouse-query"
    assert args.table == "research_candidate_daily"
    assert args.columns == "target_date,symbol,name"
    assert args.limit == 20
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
