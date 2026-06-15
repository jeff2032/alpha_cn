from __future__ import annotations

from quant_a_stock.cli import build_parser


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
            "--limit",
            "2",
        ]
    )

    assert args.command == "sync-stock-universe"
    assert args.symbols == ["688143", "688146"]
    assert args.sleep == 1.5
    assert args.limit == 2


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
            "--show-stale",
            "--output-stale",
            "data/universe/stale.csv",
        ]
    )

    assert args.command == "cache-date-status"
    assert args.target_date == "2026-06-12"
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
