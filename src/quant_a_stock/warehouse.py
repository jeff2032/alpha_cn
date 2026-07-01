from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil

import duckdb
import pandas as pd

from quant_a_stock.config import DEFAULT_PATHS


CSV_REPORT_SPECS = {
    "research_candidates": "research_candidates_*.csv",
    "daily_research_candidates": "daily_research_candidates_*.csv",
    "sentiment_scores": "sentiment_watchlist_*.csv",
    "market_themes": "market_theme_*.csv",
    "research_review_details": "research_review_details_*.csv",
    "research_review_summary": "research_review_summary_*.csv",
    "missed_opportunities": "research_review_missed_*.csv",
}

SNAPSHOT_CSV_SPECS = {
    "snapshot_research_candidates": "research_candidates.csv",
    "snapshot_sentiment_scores": "sentiment_watchlist.csv",
    "snapshot_market_themes": "market_theme.csv",
    "snapshot_scan_base_breakout_setups": "scan_base_breakout_setup.csv",
    "snapshot_scan_accumulation_setups": "scan_accumulation_setup.csv",
    "snapshot_scan_trend_pullback_setups": "scan_trend_pullback_setup.csv",
}

MARKDOWN_REPORT_SPECS = {
    "daily_research_summary": "daily_research_summary_*.md",
    "research_candidates_markdown": "research_candidates_*.md",
    "sentiment_watchlist_markdown": "sentiment_watchlist_*.md",
    "market_theme_markdown": "market_theme_*.md",
    "research_review_markdown": "research_review_*.md",
}

MIDDLE_LAYER_TABLES = [
    "research_candidate_daily",
    "stock_market_attitude_daily",
    "missed_opportunity_daily",
    "factor_diagnostics_daily",
    "strategy_review_daily",
]

WAREHOUSE_TABLES = [
    *CSV_REPORT_SPECS.keys(),
    "report_index",
    *SNAPSHOT_CSV_SPECS.keys(),
    "snapshot_index",
    *MIDDLE_LAYER_TABLES,
    "stock_universe",
    "daily_candles",
    "daily_candles_index",
    "candidate_lifecycles",
    "candidate_lifecycle_daily",
]


@dataclass(frozen=True)
class WarehouseIngestResult:
    run_id: str
    target_date: str
    db_path: Path
    parquet_root: Path
    ingested: pd.DataFrame
    status: pd.DataFrame


def warehouse_root(path: Path | None = None) -> Path:
    return path or DEFAULT_PATHS.root / "data" / "warehouse"


def warehouse_db_path(path: Path | None = None) -> Path:
    return warehouse_root(path) / "alpha_cn.duckdb"


def parquet_root(path: Path | None = None) -> Path:
    return warehouse_root(path) / "parquet"


def ingest_latest_reports(
    *,
    target_date: str,
    reports_dir: Path | None = None,
    warehouse_dir: Path | None = None,
    run_id: str | None = None,
) -> WarehouseIngestResult:
    reports_root = reports_dir or DEFAULT_PATHS.reports
    root = warehouse_root(warehouse_dir)
    root.mkdir(parents=True, exist_ok=True)
    parquet = parquet_root(warehouse_dir)
    parquet.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    resolved_run_id = run_id or f"{target_date}_{stamp}"
    ingested_at = datetime.now().isoformat(timespec="seconds")
    report_rows: list[dict] = []
    loaded_reports: dict[str, pd.DataFrame] = {}

    for table_name, pattern in CSV_REPORT_SPECS.items():
        path = _latest_file(reports_root, pattern)
        if path is None:
            report_rows.append(_report_row(resolved_run_id, target_date, table_name, None, 0, "missing", ingested_at))
            continue
        frame = pd.read_csv(path, dtype={"symbol": str})
        output = _with_metadata(
            frame,
            run_id=resolved_run_id,
            target_date=target_date,
            source_path=path,
            ingested_at=ingested_at,
        )
        _write_parquet(output, table_name, target_date=target_date, run_id=resolved_run_id, warehouse_dir=warehouse_dir)
        loaded_reports[table_name] = output
        report_rows.append(
            _report_row(resolved_run_id, target_date, table_name, path, len(output), "ingested", ingested_at)
        )

    report_rows.extend(
        _write_middle_layer_from_reports(
            loaded_reports,
            target_date=target_date,
            run_id=resolved_run_id,
            ingested_at=ingested_at,
            warehouse_dir=warehouse_dir,
        )
    )

    for report_type, pattern in MARKDOWN_REPORT_SPECS.items():
        path = _latest_file(reports_root, pattern)
        status = "indexed" if path else "missing"
        report_rows.append(_report_row(resolved_run_id, target_date, report_type, path, 0, status, ingested_at))

    report_index = pd.DataFrame(report_rows)
    _write_parquet(
        report_index,
        "report_index",
        target_date=target_date,
        run_id=resolved_run_id,
        warehouse_dir=warehouse_dir,
    )
    refresh_warehouse_views(warehouse_dir=warehouse_dir)
    status = warehouse_status(warehouse_dir=warehouse_dir)
    return WarehouseIngestResult(
        run_id=resolved_run_id,
        target_date=target_date,
        db_path=warehouse_db_path(warehouse_dir),
        parquet_root=parquet,
        ingested=report_index,
        status=status,
    )


def backfill_research_snapshots(
    *,
    snapshot_root: Path | None = None,
    warehouse_dir: Path | None = None,
    since: str | None = None,
    until: str | None = None,
    run_id: str | None = None,
) -> WarehouseIngestResult:
    snapshots_root = snapshot_root or DEFAULT_PATHS.root / "data" / "snapshots" / "research"
    root = warehouse_root(warehouse_dir)
    root.mkdir(parents=True, exist_ok=True)
    parquet = parquet_root(warehouse_dir)
    parquet.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    resolved_run_id = run_id or f"snapshots_{stamp}"
    ingested_at = datetime.now().isoformat(timespec="seconds")
    all_rows: list[dict] = []

    for snapshot_dir in _snapshot_dirs(snapshots_root, since=since, until=until):
        target_date = snapshot_dir.name
        snapshot_rows: list[dict] = []
        loaded_snapshots: dict[str, pd.DataFrame] = {}
        for table_name, filename in SNAPSHOT_CSV_SPECS.items():
            path = snapshot_dir / filename
            if not path.exists():
                row = _report_row(resolved_run_id, target_date, table_name, None, 0, "missing", ingested_at)
                snapshot_rows.append(row)
                all_rows.append(row)
                continue
            frame = pd.read_csv(path, dtype={"symbol": str})
            output = _with_metadata(
                frame,
                run_id=resolved_run_id,
                target_date=target_date,
                source_path=path,
                ingested_at=ingested_at,
            )
            _write_parquet(
                output,
                table_name,
                target_date=target_date,
                run_id=resolved_run_id,
                warehouse_dir=warehouse_dir,
            )
            loaded_snapshots[table_name] = output
            row = _report_row(resolved_run_id, target_date, table_name, path, len(output), "ingested", ingested_at)
            snapshot_rows.append(row)
            all_rows.append(row)
        middle_rows = _write_middle_layer_from_snapshots(
            loaded_snapshots,
            target_date=target_date,
            run_id=resolved_run_id,
            ingested_at=ingested_at,
            warehouse_dir=warehouse_dir,
        )
        snapshot_rows.extend(middle_rows)
        all_rows.extend(middle_rows)
        _write_parquet(
            pd.DataFrame(snapshot_rows),
            "snapshot_index",
            target_date=target_date,
            run_id=resolved_run_id,
            warehouse_dir=warehouse_dir,
        )

    ingested = pd.DataFrame(all_rows)
    refresh_warehouse_views(warehouse_dir=warehouse_dir)
    status = warehouse_status(warehouse_dir=warehouse_dir)
    return WarehouseIngestResult(
        run_id=resolved_run_id,
        target_date=_range_label(since, until),
        db_path=warehouse_db_path(warehouse_dir),
        parquet_root=parquet,
        ingested=ingested,
        status=status,
    )


def sync_stock_universe_to_warehouse(
    *,
    universe_file: Path,
    target_date: str,
    warehouse_dir: Path | None = None,
    run_id: str | None = None,
) -> WarehouseIngestResult:
    root = warehouse_root(warehouse_dir)
    root.mkdir(parents=True, exist_ok=True)
    parquet = parquet_root(warehouse_dir)
    parquet.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    resolved_run_id = run_id or f"stock_universe_{target_date}_{stamp}"
    ingested_at = datetime.now().isoformat(timespec="seconds")
    frame = pd.read_csv(universe_file, dtype={"symbol": str})
    output = _with_metadata(
        frame,
        run_id=resolved_run_id,
        target_date=target_date,
        source_path=universe_file,
        ingested_at=ingested_at,
    )
    _write_parquet(
        output,
        "stock_universe",
        target_date=target_date,
        run_id=resolved_run_id,
        warehouse_dir=warehouse_dir,
    )
    ingested = pd.DataFrame(
        [_report_row(resolved_run_id, target_date, "stock_universe", universe_file, len(output), "ingested", ingested_at)]
    )
    refresh_warehouse_views(warehouse_dir=warehouse_dir)
    status = warehouse_status(warehouse_dir=warehouse_dir)
    return WarehouseIngestResult(
        run_id=resolved_run_id,
        target_date=target_date,
        db_path=warehouse_db_path(warehouse_dir),
        parquet_root=parquet,
        ingested=ingested,
        status=status,
    )


def sync_daily_candles_to_warehouse(
    *,
    symbols: list[str] | None = None,
    universe_file: Path | None = None,
    cache_dir: Path | None = None,
    source: str = "akshare",
    since: str | None = None,
    until: str | None = None,
    target_date: str | None = None,
    warehouse_dir: Path | None = None,
    run_id: str | None = None,
    limit: int | None = None,
    force: bool = False,
) -> WarehouseIngestResult:
    root = warehouse_root(warehouse_dir)
    root.mkdir(parents=True, exist_ok=True)
    parquet = parquet_root(warehouse_dir)
    parquet.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    resolved_target_date = target_date or datetime.now().date().isoformat()
    resolved_run_id = run_id or f"daily_candles_{resolved_target_date}_{stamp}"
    ingested_at = datetime.now().isoformat(timespec="seconds")
    cache_root = cache_dir or DEFAULT_PATHS.data_cache
    daily_root = cache_root / source / "daily"
    selected_symbols = _resolve_symbols(symbols=symbols, universe_file=universe_file, daily_root=daily_root)
    if limit is not None:
        selected_symbols = selected_symbols[: max(0, limit)]

    existing_last = _daily_candles_last_by_symbol(warehouse_dir=warehouse_dir)
    rows: list[dict] = []
    since_ts = pd.Timestamp(since).normalize() if since else None
    until_ts = pd.Timestamp(until).normalize() if until else None

    for symbol in selected_symbols:
        path = daily_root / f"{symbol}.csv"
        if not path.exists():
            rows.append(
                _daily_candle_index_row(
                    resolved_run_id,
                    resolved_target_date,
                    symbol,
                    path,
                    0,
                    "",
                    "",
                    "missing",
                    ingested_at,
                )
            )
            continue
        csv_last = _last_csv_timestamp(path)
        last_known = existing_last.get(symbol)
        if (
            not force
            and csv_last is not None
            and last_known
            and pd.Timestamp(last_known).normalize() >= csv_last.normalize()
            and _daily_symbol_parquet_path(symbol, warehouse_dir=warehouse_dir).exists()
        ):
            rows.append(
                _daily_candle_index_row(
                    resolved_run_id,
                    resolved_target_date,
                    symbol,
                    path,
                    0,
                    "",
                    csv_last.date().isoformat(),
                    "skipped",
                    ingested_at,
                )
            )
            continue
        frame = pd.read_csv(path, dtype={"symbol": str})
        if "timestamp" not in frame.columns:
            rows.append(
                _daily_candle_index_row(
                    resolved_run_id,
                    resolved_target_date,
                    symbol,
                    path,
                    0,
                    "",
                    "",
                    "invalid",
                    ingested_at,
                )
            )
            continue
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
        frame = frame.dropna(subset=["timestamp"]).sort_values("timestamp").drop_duplicates("timestamp")
        if since_ts is not None:
            frame = frame[frame["timestamp"] >= since_ts]
        if until_ts is not None:
            frame = frame[frame["timestamp"] <= until_ts]
        if "symbol" not in frame.columns:
            frame["symbol"] = symbol
        output = _with_metadata(
            frame,
            run_id=resolved_run_id,
            target_date=resolved_target_date,
            source_path=path,
            ingested_at=ingested_at,
        )
        _write_symbol_parquet(output, "daily_candles", symbol=symbol, warehouse_dir=warehouse_dir)
        first_timestamp = _clean_date(output["timestamp"].min()) if not output.empty else ""
        last_timestamp = _clean_date(output["timestamp"].max()) if not output.empty else ""
        rows.append(
            _daily_candle_index_row(
                resolved_run_id,
                resolved_target_date,
                symbol,
                path,
                len(output),
                first_timestamp,
                last_timestamp,
                "synced",
                ingested_at,
            )
        )

    index = pd.DataFrame(rows)
    _write_run_parquet(
        index,
        "daily_candles_index",
        run_id=resolved_run_id,
        warehouse_dir=warehouse_dir,
    )
    refresh_warehouse_views(warehouse_dir=warehouse_dir)
    status = warehouse_status(warehouse_dir=warehouse_dir)
    return WarehouseIngestResult(
        run_id=resolved_run_id,
        target_date=resolved_target_date,
        db_path=warehouse_db_path(warehouse_dir),
        parquet_root=parquet,
        ingested=index,
        status=status,
    )


def sync_candidate_lifecycles_to_warehouse(
    *,
    lifecycles: pd.DataFrame,
    daily: pd.DataFrame,
    target_date: str,
    warehouse_dir: Path | None = None,
    run_id: str | None = None,
) -> WarehouseIngestResult:
    root = warehouse_root(warehouse_dir)
    root.mkdir(parents=True, exist_ok=True)
    parquet = parquet_root(warehouse_dir)
    parquet.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    resolved_run_id = run_id or f"candidate_lifecycle_{target_date}_{stamp}"
    ingested_at = datetime.now().isoformat(timespec="seconds")
    rows = []

    for table_name, frame in (
        ("candidate_lifecycles", lifecycles),
        ("candidate_lifecycle_daily", daily),
    ):
        output = frame.copy()
        output["warehouse_run_id"] = resolved_run_id
        output["warehouse_target_date"] = target_date
        output["warehouse_source_path"] = "generated:candidate_lifecycle"
        output["warehouse_ingested_at"] = ingested_at
        _write_parquet(
            output,
            table_name,
            target_date=target_date,
            run_id=resolved_run_id,
            warehouse_dir=warehouse_dir,
        )
        rows.append(_report_row(resolved_run_id, target_date, table_name, None, len(output), "ingested", ingested_at))

    ingested = pd.DataFrame(rows)
    refresh_warehouse_views(warehouse_dir=warehouse_dir)
    status = warehouse_status(warehouse_dir=warehouse_dir)
    return WarehouseIngestResult(
        run_id=resolved_run_id,
        target_date=target_date,
        db_path=warehouse_db_path(warehouse_dir),
        parquet_root=parquet,
        ingested=ingested,
        status=status,
    )


def _write_middle_layer_from_reports(
    frames: dict[str, pd.DataFrame],
    *,
    target_date: str,
    run_id: str,
    ingested_at: str,
    warehouse_dir: Path | None,
) -> list[dict]:
    rows: list[dict] = []
    candidates = frames.get("research_candidates")
    if candidates is not None and not candidates.empty:
        rows.append(
            _write_middle_frame(
                _build_research_candidate_daily(candidates, target_date=target_date),
                "research_candidate_daily",
                target_date=target_date,
                run_id=run_id,
                source_path="derived:research_candidates",
                ingested_at=ingested_at,
                warehouse_dir=warehouse_dir,
            )
        )
        rows.append(
            _write_middle_frame(
                _build_stock_market_attitude_daily(candidates, target_date=target_date),
                "stock_market_attitude_daily",
                target_date=target_date,
                run_id=run_id,
                source_path="derived:research_candidates",
                ingested_at=ingested_at,
                warehouse_dir=warehouse_dir,
            )
        )

    missed = frames.get("missed_opportunities")
    if missed is not None and not missed.empty:
        rows.append(
            _write_middle_frame(
                _build_missed_opportunity_daily(missed, target_date=target_date),
                "missed_opportunity_daily",
                target_date=target_date,
                run_id=run_id,
                source_path="derived:research_review_missed",
                ingested_at=ingested_at,
                warehouse_dir=warehouse_dir,
            )
        )

    summary = frames.get("research_review_summary")
    if summary is not None and not summary.empty:
        rows.append(
            _write_middle_frame(
                _build_factor_diagnostics_daily(summary, target_date=target_date),
                "factor_diagnostics_daily",
                target_date=target_date,
                run_id=run_id,
                source_path="derived:research_review_summary",
                ingested_at=ingested_at,
                warehouse_dir=warehouse_dir,
            )
        )
        rows.append(
            _write_middle_frame(
                _build_strategy_review_daily(summary, target_date=target_date),
                "strategy_review_daily",
                target_date=target_date,
                run_id=run_id,
                source_path="derived:research_review_summary",
                ingested_at=ingested_at,
                warehouse_dir=warehouse_dir,
            )
        )
    return [row for row in rows if row]


def _write_middle_layer_from_snapshots(
    frames: dict[str, pd.DataFrame],
    *,
    target_date: str,
    run_id: str,
    ingested_at: str,
    warehouse_dir: Path | None,
) -> list[dict]:
    candidates = frames.get("snapshot_research_candidates")
    if candidates is None or candidates.empty:
        return []
    return [
        _write_middle_frame(
            _build_research_candidate_daily(candidates, target_date=target_date),
            "research_candidate_daily",
            target_date=target_date,
            run_id=run_id,
            source_path="derived:snapshot_research_candidates",
            ingested_at=ingested_at,
            warehouse_dir=warehouse_dir,
        ),
        _write_middle_frame(
            _build_stock_market_attitude_daily(candidates, target_date=target_date),
            "stock_market_attitude_daily",
            target_date=target_date,
            run_id=run_id,
            source_path="derived:snapshot_research_candidates",
            ingested_at=ingested_at,
            warehouse_dir=warehouse_dir,
        ),
    ]


def _write_middle_frame(
    frame: pd.DataFrame,
    table_name: str,
    *,
    target_date: str,
    run_id: str,
    source_path: str,
    ingested_at: str,
    warehouse_dir: Path | None,
) -> dict:
    output = frame.copy()
    if output.empty:
        return _report_row(run_id, target_date, table_name, None, 0, "empty", ingested_at)
    if "symbol" in output.columns:
        output["symbol"] = output["symbol"].astype(str).str.zfill(6)
    output["warehouse_run_id"] = run_id
    output["warehouse_target_date"] = target_date
    output["warehouse_source_path"] = source_path
    output["warehouse_ingested_at"] = ingested_at
    _write_parquet(output, table_name, target_date=target_date, run_id=run_id, warehouse_dir=warehouse_dir)
    return _report_row(run_id, target_date, table_name, None, len(output), "derived", ingested_at)


def refresh_warehouse_views(*, warehouse_dir: Path | None = None) -> None:
    root = warehouse_root(warehouse_dir)
    db_path = warehouse_db_path(warehouse_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db_path)) as conn:
        for table_name in WAREHOUSE_TABLES:
            table_root = parquet_root(warehouse_dir) / table_name
            if not table_root.exists():
                continue
            pattern = _duckdb_path(table_root / "**" / "*.parquet")
            conn.execute(
                f"""
                CREATE OR REPLACE VIEW {table_name} AS
                SELECT * FROM read_parquet('{pattern}', union_by_name=true)
                """
            )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS warehouse_meta (
                key VARCHAR PRIMARY KEY,
                value VARCHAR
            )
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO warehouse_meta VALUES ('warehouse_root', ?)",
            [str(root)],
        )


def warehouse_status(*, warehouse_dir: Path | None = None) -> pd.DataFrame:
    db_path = warehouse_db_path(warehouse_dir)
    if not db_path.exists():
        return pd.DataFrame(columns=_status_columns())
    rows = []
    with duckdb.connect(str(db_path), read_only=True) as conn:
        views = _warehouse_views(conn)
        for table_name in WAREHOUSE_TABLES:
            if table_name not in views:
                rows.append(_empty_status_row(table_name))
                continue
            rows.append(_table_status(conn, table_name))
    return pd.DataFrame(rows)


def warehouse_review(
    *,
    since: str | None = None,
    until: str | None = None,
    warehouse_dir: Path | None = None,
) -> dict[str, pd.DataFrame]:
    db_path = warehouse_db_path(warehouse_dir)
    if not db_path.exists():
        return {
            "tier": pd.DataFrame(),
            "bucket": pd.DataFrame(),
            "miss_risk": pd.DataFrame(),
            "reports": pd.DataFrame(),
        }
    where, params = _date_filter("signal_date", since=since, until=until)
    with duckdb.connect(str(db_path), read_only=True) as conn:
        views = _warehouse_views(conn)
        tier = pd.DataFrame()
        bucket = pd.DataFrame()
        miss_risk = pd.DataFrame()
        reports = pd.DataFrame()
        if "research_review_details" in views:
            columns = _view_columns(conn, "research_review_details")
            count_3d_expr = "COUNT(ret_3d)" if "ret_3d" in columns else "0"
            win_rate_3d_expr = (
                "AVG(CASE WHEN ret_3d IS NULL THEN NULL WHEN ret_3d > 0 THEN 1 ELSE 0 END)"
                if "ret_3d" in columns
                else "NULL"
            )
            avg_ret_3d_expr = "AVG(ret_3d)" if "ret_3d" in columns else "NULL"
            tier = conn.execute(
                f"""
                SELECT
                    tier,
                    COUNT(*) AS count,
                    COUNT(next_ret) AS count_1d,
                    {count_3d_expr} AS count_3d,
                    AVG(next_ret) AS avg_ret_1d,
                    MEDIAN(next_ret) AS median_ret_1d,
                    AVG(CASE WHEN next_ret IS NULL THEN NULL WHEN next_ret > 0 THEN 1 ELSE 0 END) AS win_rate_1d,
                    {win_rate_3d_expr} AS win_rate_3d,
                    {avg_ret_3d_expr} AS avg_ret_3d
                FROM research_review_details
                {where}
                GROUP BY tier
                ORDER BY
                    CASE tier
                        WHEN 'A1' THEN 1
                        WHEN 'A2' THEN 2
                        WHEN 'A3' THEN 3
                        WHEN 'B1' THEN 4
                        WHEN 'B2' THEN 5
                        ELSE 9
                    END
                """,
                params,
            ).df()
            bucket_expr = (
                """
                COALESCE(
                    model_bucket,
                    CASE
                        WHEN tier IN ('A', 'A1', 'A2') THEN 'A1/A2_early_setup'
                        WHEN tier = 'A3' THEN 'A3_trend_follow'
                        WHEN tier IN ('B', 'B1', 'B2') THEN 'B_watchlist'
                        ELSE 'other'
                    END
                )
                """
                if "model_bucket" in columns
                else """
                CASE
                    WHEN tier IN ('A', 'A1', 'A2') THEN 'A1/A2_early_setup'
                    WHEN tier = 'A3' THEN 'A3_trend_follow'
                    WHEN tier IN ('B', 'B1', 'B2') THEN 'B_watchlist'
                    ELSE 'other'
                END
                """
            )
            bucket = conn.execute(
                f"""
                WITH normalized AS (
                    SELECT
                        {bucket_expr} AS model_bucket,
                        next_ret,
                        {"ret_3d" if "ret_3d" in columns else "NULL"} AS ret_3d
                    FROM research_review_details
                    {where}
                )
                SELECT
                    model_bucket,
                    COUNT(*) AS count,
                    AVG(next_ret) AS avg_ret_1d,
                    MEDIAN(next_ret) AS median_ret_1d,
                    AVG(CASE WHEN next_ret IS NULL THEN NULL WHEN next_ret > 0 THEN 1 ELSE 0 END) AS win_rate_1d,
                    {win_rate_3d_expr} AS win_rate_3d,
                    {avg_ret_3d_expr} AS avg_ret_3d
                FROM normalized
                GROUP BY model_bucket
                ORDER BY
                    CASE model_bucket
                        WHEN 'A1/A2_early_setup' THEN 1
                        WHEN 'A3_trend_follow' THEN 2
                        WHEN 'B_watchlist' THEN 3
                        ELSE 9
                    END
                """,
                params,
            ).df()
        if "missed_opportunities" in views:
            miss_where, miss_params = _date_filter("signal_date", since=since, until=until)
            miss_risk = conn.execute(
                f"""
                SELECT
                    risk_level,
                    miss_reason,
                    COUNT(*) AS count,
                    AVG(next_ret) AS avg_next_ret
                FROM missed_opportunities
                {miss_where}
                GROUP BY risk_level, miss_reason
                ORDER BY count DESC
                """,
                miss_params,
            ).df()
        if "report_index" in views:
            report_where, report_params = _date_filter("warehouse_target_date", since=since, until=until)
            reports = conn.execute(
                f"""
                SELECT warehouse_target_date, report_type, status, source_path, row_count
                FROM report_index
                {report_where}
                ORDER BY warehouse_target_date DESC, report_type
                """,
                report_params,
            ).df()
    return {"tier": tier, "bucket": bucket, "miss_risk": miss_risk, "reports": reports}


def _build_research_candidate_daily(frame: pd.DataFrame, *, target_date: str) -> pd.DataFrame:
    output = pd.DataFrame()
    output["target_date"] = _constant_series(frame, target_date)
    output["symbol"] = _column(frame, "symbol", default="").astype(str).str.zfill(6)
    output["name"] = _column(frame, "name", "名称", default="")
    output["tier"] = _column(frame, "research_tier", "tier", default="")
    output["action_bucket"] = _column(frame, "action_bucket", default="")
    output["model_bucket"] = output.apply(lambda row: _candidate_model_bucket(row["tier"], row["action_bucket"]), axis=1)
    output["expected_horizon"] = output.apply(lambda row: _expected_horizon(row["tier"], row["action_bucket"]), axis=1)
    output["research_score"] = _numeric_column(frame, "research_score")
    output["shape_score"] = _numeric_column(frame, "score")
    output["sentiment_score"] = _numeric_column(frame, "sentiment_score")
    output["stage"] = _column(frame, "stage", default="")
    output["matched_theme"] = _column(frame, "matched_theme", default="")
    output["theme_rank"] = _numeric_column(frame, "theme_rank")
    output["co_rise_count"] = _numeric_column(frame, "co_rise_count")
    output["risk_level"] = _column(frame, "risk_level", default="")
    output["risk_tags"] = _column(frame, "risk_tags", default="")
    output["reason_tags"] = frame.apply(_candidate_reason_tags, axis=1)
    output["latest_core_news"] = _column(frame, "latest_core_news", default="")
    output["upgrade_hint"] = _column(frame, "upgrade_hint", default="")
    attitude = frame.apply(_market_attitude_parts, axis=1, result_type="expand")
    output["market_attitude_label"] = attitude["label"]
    output["market_attitude_reasons"] = attitude["reasons"]
    output["market_attitude_risks"] = attitude["risks"]
    output["next_status"] = ""
    return output


def _build_stock_market_attitude_daily(frame: pd.DataFrame, *, target_date: str) -> pd.DataFrame:
    attitude = frame.apply(_market_attitude_parts, axis=1, result_type="expand")
    output = pd.DataFrame()
    output["target_date"] = _constant_series(frame, target_date)
    output["symbol"] = _column(frame, "symbol", default="").astype(str).str.zfill(6)
    output["name"] = _column(frame, "name", "名称", default="")
    output["attention_score"] = attitude["attention_score"]
    output["money_confirmation_score"] = attitude["money_confirmation_score"]
    output["theme_confirmation_score"] = attitude["theme_confirmation_score"]
    output["price_action_attitude_score"] = attitude["price_action_attitude_score"]
    output["event_score"] = attitude["event_score"]
    output["risk_attitude_score"] = attitude["risk_attitude_score"]
    output["crowding_risk_score"] = attitude["crowding_risk_score"]
    output["attitude_label"] = attitude["label"]
    output["attitude_reasons"] = attitude["reasons"]
    output["attitude_risks"] = attitude["risks"]
    output["data_sources"] = "candidate, sentiment, theme, price_volume, risk_notice"
    return output


def _build_missed_opportunity_daily(frame: pd.DataFrame, *, target_date: str) -> pd.DataFrame:
    output = pd.DataFrame()
    output["target_date"] = _constant_series(frame, target_date)
    output["signal_date"] = _column(frame, "signal_date", default=target_date)
    output["next_date"] = _column(frame, "next_date", default="")
    output["symbol"] = _column(frame, "symbol", default="").astype(str).str.zfill(6)
    output["name"] = _column(frame, "name", "名称", default="")
    output["next_ret"] = _numeric_column(frame, "next_ret")
    output["model_bucket"] = _column(frame, "model_bucket", default="miss_learnable")
    output["is_learnable"] = _column(frame, "is_learnable", default="")
    output["miss_reason"] = _column(frame, "miss_reason", default="")
    output["risk_level"] = _column(frame, "risk_level", default="")
    output["risk_tags"] = _column(frame, "risk_tags", default="")
    output["primary_risk_tag"] = _column(frame, "primary_risk_tag", default="")
    output["action_hint"] = _column(frame, "action_hint", default="")
    return output


def _build_factor_diagnostics_daily(frame: pd.DataFrame, *, target_date: str) -> pd.DataFrame:
    output = frame.copy()
    output.insert(0, "target_date", target_date)
    output["diagnostic_type"] = _column(output, "table", default="")
    output["factor_name"] = output.apply(_factor_name, axis=1)
    output["horizon"] = _column(output, "horizon", default="")
    return output


def _build_strategy_review_daily(frame: pd.DataFrame, *, target_date: str) -> pd.DataFrame:
    if "table" not in frame.columns:
        return pd.DataFrame(columns=["target_date", "review_type", "segment_name", "horizon", "verdict", "review_note"])
    output = frame[frame["table"].astype(str).isin(_strategy_review_tables())].copy()
    if output.empty:
        return pd.DataFrame(columns=["target_date", "review_type", "segment_name", "horizon", "verdict", "review_note"])
    output.insert(0, "target_date", target_date)
    output["review_type"] = output["table"].astype(str)
    output["segment_name"] = output.apply(_factor_name, axis=1)
    output["horizon"] = _column(output, "horizon", default="")
    output["verdict"] = output.apply(_strategy_verdict, axis=1)
    output["review_note"] = output.apply(_strategy_review_note, axis=1)
    return output


def _strategy_review_tables() -> set[str]:
    return {
        "by_tier",
        "by_tier_horizon",
        "by_model_bucket",
        "by_model_bucket_horizon",
        "by_action_bucket",
        "by_action_bucket_horizon",
        "by_stage",
        "by_stage_horizon",
        "loss_attribution",
        "miss_learnability",
        "portfolio",
        "market_capture",
    }


def _candidate_model_bucket(tier: object, action_bucket: object) -> str:
    tier_text = str(tier or "")
    bucket_text = str(action_bucket or "")
    if tier_text in {"A1", "A2"}:
        return "A1/A2_early_setup"
    if tier_text == "A3":
        return "A3_trend_follow"
    if tier_text.startswith("B") or "B2" in bucket_text:
        return "B_watchlist"
    return "other"


def _expected_horizon(tier: object, action_bucket: object) -> str:
    tier_text = str(tier or "")
    bucket_text = str(action_bucket or "")
    if tier_text == "A1" or "A1" in bucket_text:
        return "10-30d"
    if tier_text == "A2" or "A2" in bucket_text:
        return "3-15d"
    if tier_text == "A3" or "A3" in bucket_text:
        return "1-10d"
    if "B2a" in bucket_text:
        return "3-10d"
    if "B2b" in bucket_text:
        return "1-5d"
    if tier_text.startswith("B"):
        return "1-10d"
    return "observe"


def _candidate_reason_tags(row: pd.Series) -> str:
    tags: list[str] = []
    stage = str(row.get("stage", "") or "")
    stage_map = {
        "accumulation": "低位蓄势",
        "pre_breakout": "突破前压缩",
        "near_breakout": "接近突破",
        "breakout": "突破确认",
        "trend_pullback": "趋势回踩",
        "trend_resume": "趋势再启动",
    }
    if stage in stage_map:
        tags.append(stage_map[stage])
    theme = str(row.get("matched_theme", "") or "")
    if theme:
        tags.append(f"主线:{theme}")
    if _safe_float(row.get("co_rise_count")) >= 8:
        tags.append("同主题共振")
    if _safe_float(row.get("core_news_count")) > 0:
        tags.append("核心新闻")
    sentiment = _safe_float(row.get("sentiment_score"))
    if sentiment >= 70:
        tags.append("情绪强")
    elif sentiment >= 60:
        tags.append("情绪温和")
    volume_ratio = _safe_float(row.get("volume_ratio"))
    if volume_ratio >= 1.2:
        tags.append("量能确认")
    elif 0 < volume_ratio < 0.8:
        tags.append("量能不足")
    if bool(row.get("in_limit_pool", False)):
        tags.append("涨停池")
    elif bool(row.get("in_strong_pool", False)):
        tags.append("强势池")
    return "；".join(tags)


def _market_attitude_parts(row: pd.Series) -> dict:
    attention = _attention_score(row)
    money = _money_confirmation_score(row)
    theme = _theme_confirmation_score(row)
    price_action = _price_action_attitude_score(row)
    event = _event_score(row)
    risk = _risk_attitude_score(row)
    crowding = _crowding_risk_score(row)
    label = _attitude_label(attention, money, theme, price_action, event, risk, crowding)
    reasons = _attitude_reasons(row, attention, money, theme, price_action, event)
    risks = _attitude_risks(row, risk, crowding)
    return {
        "attention_score": round(attention, 2),
        "money_confirmation_score": round(money, 2),
        "theme_confirmation_score": round(theme, 2),
        "price_action_attitude_score": round(price_action, 2),
        "event_score": round(event, 2),
        "risk_attitude_score": round(risk, 2),
        "crowding_risk_score": round(crowding, 2),
        "label": label,
        "reasons": "；".join(reasons),
        "risks": "；".join(risks),
    }


def _attention_score(row: pd.Series) -> float:
    sentiment = _safe_float(row.get("sentiment_score"))
    hot_rank = _safe_float(row.get("hot_rank"))
    hot_rank_score = max(0.0, 100.0 - hot_rank) if hot_rank > 0 else 0.0
    news_score = min(100.0, _safe_float(row.get("news_count")) * 8 + _safe_float(row.get("core_news_count")) * 25)
    return _clip(max(sentiment, hot_rank_score, news_score))


def _money_confirmation_score(row: pd.Series) -> float:
    volume_ratio = _safe_float(row.get("volume_ratio"))
    amount_ma20 = _safe_float(row.get("amount_ma20"))
    amount_score = 0.0
    if amount_ma20 >= 500_000_000:
        amount_score = 30.0
    elif amount_ma20 >= 200_000_000:
        amount_score = 20.0
    elif amount_ma20 >= 80_000_000:
        amount_score = 10.0
    volume_score = min(45.0, max(0.0, volume_ratio - 0.7) * 35.0) if volume_ratio > 0 else 0.0
    pool_score = 20.0 if bool(row.get("in_limit_pool", False)) else (12.0 if bool(row.get("in_strong_pool", False)) else 0.0)
    stage_score = 10.0 if str(row.get("stage", "")) in {"near_breakout", "breakout", "trend_resume"} else 0.0
    return _clip(amount_score + volume_score + pool_score + stage_score)


def _theme_confirmation_score(row: pd.Series) -> float:
    score = 0.0
    theme_rank = _safe_float(row.get("theme_rank"), default=99.0)
    if theme_rank > 0 and theme_rank <= 10:
        score += max(20.0, 70.0 - (theme_rank - 1.0) * 5.0)
    if str(row.get("matched_theme", "") or ""):
        score = max(score, 55.0)
    score += min(30.0, _safe_float(row.get("co_rise_count")) * 2.5)
    return _clip(score)


def _price_action_attitude_score(row: pd.Series) -> float:
    stage = str(row.get("stage", "") or "")
    stage_score = {
        "accumulation": 45.0,
        "pre_breakout": 55.0,
        "near_breakout": 65.0,
        "breakout": 70.0,
        "trend_pullback": 55.0,
        "trend_resume": 70.0,
    }.get(stage, 35.0)
    ret20 = _safe_float(row.get("ret_20_pct"))
    volume_ratio = _safe_float(row.get("volume_ratio"))
    if ret20 > 0.24 and volume_ratio > 2.2:
        stage_score -= 20.0
    elif ret20 < 0.15 and volume_ratio >= 1.0:
        stage_score += 8.0
    return _clip(stage_score)


def _event_score(row: pd.Series) -> float:
    core = _safe_float(row.get("core_news_count"))
    reports = _safe_float(row.get("research_report_count"))
    latest_core = str(row.get("latest_core_news", "") or "").strip()
    return _clip(core * 35.0 + reports * 12.0 + (20.0 if latest_core else 0.0))


def _risk_attitude_score(row: pd.Series) -> float:
    risk_level = str(row.get("risk_level", "") or "")
    level_score = {"低": 0.0, "中": 25.0, "中高": 55.0, "高": 85.0}.get(risk_level, 10.0)
    notice_score = min(50.0, _safe_float(row.get("risk_notice_count")) * 25.0)
    penalty_score = min(60.0, _safe_float(row.get("total_penalty")) * 2.5)
    return _clip(max(level_score, notice_score, penalty_score))


def _crowding_risk_score(row: pd.Series) -> float:
    score = 0.0
    ret20 = _safe_float(row.get("ret_20_pct"))
    volume_ratio = _safe_float(row.get("volume_ratio"))
    monthly_position = _safe_float(row.get("monthly_position_pct"))
    price_position = _safe_float(row.get("price_position_pct"))
    if ret20 > 0.30:
        score += 35.0
    elif ret20 > 0.18:
        score += 20.0
    if volume_ratio > 4.0:
        score += 35.0
    elif volume_ratio > 2.2:
        score += 20.0
    if monthly_position > 0.75:
        score += 20.0
    if price_position > 0.82:
        score += 20.0
    return _clip(score)


def _attitude_label(
    attention: float,
    money: float,
    theme: float,
    price_action: float,
    event: float,
    risk: float,
    crowding: float,
) -> str:
    if risk >= 70:
        return "风险压制"
    if crowding >= 70 and money < 55:
        return "过热分歧"
    if attention >= 65 and money >= 60 and (theme >= 55 or event >= 55) and price_action >= 55:
        return "强确认"
    if money >= 50 and (theme >= 45 or attention >= 55 or event >= 45):
        return "温和确认"
    if attention >= 65 and money < 45:
        return "虚热"
    if attention < 45 and money < 45:
        return "冷启动"
    return "观察确认"


def _attitude_reasons(
    row: pd.Series,
    attention: float,
    money: float,
    theme: float,
    price_action: float,
    event: float,
) -> list[str]:
    reasons: list[str] = []
    if attention >= 65:
        reasons.append("热度较高")
    if money >= 60:
        reasons.append("资金承接较强")
    elif money >= 50:
        reasons.append("资金温和确认")
    if theme >= 55:
        theme_name = str(row.get("matched_theme", "") or "")
        reasons.append(f"主题共振{':' + theme_name if theme_name else ''}")
    if price_action >= 65:
        reasons.append("盘面走势确认")
    if event >= 55:
        reasons.append("核心事件催化")
    if not reasons:
        reasons.append("暂无强证据")
    return reasons


def _attitude_risks(row: pd.Series, risk: float, crowding: float) -> list[str]:
    risks: list[str] = []
    if risk >= 55:
        risks.append(str(row.get("risk_tags", "") or "风险项偏多"))
    if crowding >= 55:
        risks.append("拥挤度偏高")
    if _safe_float(row.get("ret_20_pct")) > 0.18:
        risks.append("20日涨幅偏热")
    if _safe_float(row.get("volume_ratio")) > 2.2:
        risks.append("量能偏热")
    return [item for item in risks if item]


def _factor_name(row: pd.Series) -> str:
    for column in (
        "tier",
        "action_bucket",
        "model_bucket",
        "stage",
        "loss_reason",
        "miss_reason",
        "risk_level",
        "table",
    ):
        value = str(row.get(column, "") or "").strip()
        if value:
            return value
    return "overall"


def _strategy_verdict(row: pd.Series) -> str:
    count = _safe_float(row.get("count"))
    avg_ret = _first_numeric(row, "avg_ret", "avg_next_ret", "avg_preferred_ret")
    win_rate = _first_numeric(row, "win_rate")
    loss_rate = _first_numeric(row, "lt_minus5_rate", "loss_rate")
    if count and count < 3:
        return "样本不足"
    if avg_ret >= 0.03 and (win_rate == 0 or win_rate >= 0.55):
        return "有效"
    if avg_ret <= -0.02 or loss_rate >= 0.25:
        return "拖后腿"
    return "中性"


def _strategy_review_note(row: pd.Series) -> str:
    verdict = _strategy_verdict(row)
    name = _factor_name(row)
    horizon = str(row.get("horizon", "") or "")
    suffix = f"，周期 {horizon}" if horizon else ""
    if verdict == "有效":
        return f"{name}{suffix} 表现较好，保留为正向证据。"
    if verdict == "拖后腿":
        return f"{name}{suffix} 表现偏弱，后续复盘风险标签和过滤条件。"
    if verdict == "样本不足":
        return f"{name}{suffix} 样本不足，只记录不下结论。"
    return f"{name}{suffix} 表现中性，继续观察。"


def _constant_series(frame: pd.DataFrame, value: object) -> pd.Series:
    return pd.Series([value] * len(frame), index=frame.index)


def _column(frame: pd.DataFrame, *names: str, default: object = "") -> pd.Series:
    for name in names:
        if name in frame.columns:
            return frame[name].fillna(default)
    return _constant_series(frame, default)


def _numeric_column(frame: pd.DataFrame, *names: str, default: float = 0.0) -> pd.Series:
    return pd.to_numeric(_column(frame, *names, default=default), errors="coerce").fillna(default)


def _safe_float(value: object, default: float = 0.0) -> float:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return default
    return float(parsed)


def _first_numeric(row: pd.Series, *names: str) -> float:
    for name in names:
        if name in row.index:
            value = _safe_float(row.get(name))
            if value:
                return value
    return 0.0


def _clip(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, float(value)))


def _latest_file(root: Path, pattern: str) -> Path | None:
    if not root.exists():
        return None
    matches = sorted(root.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def _with_metadata(
    frame: pd.DataFrame,
    *,
    run_id: str,
    target_date: str,
    source_path: Path,
    ingested_at: str,
) -> pd.DataFrame:
    output = frame.copy()
    if "symbol" in output.columns:
        output["symbol"] = output["symbol"].astype(str).str.zfill(6)
    output["warehouse_run_id"] = run_id
    output["warehouse_target_date"] = target_date
    output["warehouse_source_path"] = str(source_path)
    output["warehouse_ingested_at"] = ingested_at
    return output


def _write_parquet(
    frame: pd.DataFrame,
    table_name: str,
    *,
    target_date: str,
    run_id: str,
    warehouse_dir: Path | None,
) -> Path:
    output_dir = parquet_root(warehouse_dir) / table_name / f"target_date={target_date}"
    _replace_target_partition(output_dir, warehouse_dir=warehouse_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{_safe_filename(run_id)}.parquet"
    with duckdb.connect() as conn:
        conn.register("warehouse_frame", frame)
        conn.execute(f"COPY warehouse_frame TO '{_duckdb_path(output_path)}' (FORMAT PARQUET)")
    return output_path


def _report_row(
    run_id: str,
    target_date: str,
    report_type: str,
    path: Path | None,
    row_count: int,
    status: str,
    ingested_at: str,
) -> dict:
    return {
        "warehouse_run_id": run_id,
        "warehouse_target_date": target_date,
        "report_type": report_type,
        "source_path": str(path) if path else "",
        "row_count": int(row_count),
        "status": status,
        "warehouse_ingested_at": ingested_at,
    }


def _warehouse_views(conn: duckdb.DuckDBPyConnection) -> set[str]:
    rows = conn.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'main'
        """
    ).fetchall()
    return {str(row[0]) for row in rows}


def _view_columns(conn: duckdb.DuckDBPyConnection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    return {str(row[1]) for row in rows}


def _table_status(conn: duckdb.DuckDBPyConnection, table_name: str) -> dict:
    columns = _view_columns(conn, table_name)
    row = _empty_status_row(table_name)
    row["rows"] = int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])
    if "warehouse_target_date" in columns:
        result = conn.execute(
            f"""
            SELECT
                COUNT(DISTINCT warehouse_target_date),
                MIN(warehouse_target_date),
                MAX(warehouse_target_date)
            FROM {table_name}
            """
        ).fetchone()
        row["target_dates"] = int(result[0])
        row["first_target_date"] = _clean_date(result[1])
        row["last_target_date"] = _clean_date(result[2])
    if "symbol" in columns:
        row["symbols"] = int(conn.execute(f"SELECT COUNT(DISTINCT symbol) FROM {table_name}").fetchone()[0])
    if "timestamp" in columns:
        result = conn.execute(f"SELECT MIN(timestamp), MAX(timestamp) FROM {table_name}").fetchone()
        row["first_timestamp"] = _clean_date(result[0])
        row["last_timestamp"] = _clean_date(result[1])
    return row


def _empty_status_row(table_name: str) -> dict:
    return {
        "table": table_name,
        "rows": 0,
        "target_dates": 0,
        "first_target_date": "",
        "last_target_date": "",
        "symbols": 0,
        "first_timestamp": "",
        "last_timestamp": "",
    }


def _status_columns() -> list[str]:
    return [
        "table",
        "rows",
        "target_dates",
        "first_target_date",
        "last_target_date",
        "symbols",
        "first_timestamp",
        "last_timestamp",
    ]


def _date_filter(column: str, *, since: str | None, until: str | None) -> tuple[str, list[str]]:
    clauses = []
    params = []
    if since:
        clauses.append(f"{column} >= ?")
        params.append(since)
    if until:
        clauses.append(f"{column} <= ?")
        params.append(until)
    if not clauses:
        return "", params
    return "WHERE " + " AND ".join(clauses), params


def _duckdb_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace("'", "''")


def _safe_filename(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)


def _safe_symbol(value: str) -> str:
    return str(value).strip().zfill(6)


def _clean_date(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value)


def _replace_target_partition(output_dir: Path, *, warehouse_dir: Path | None) -> None:
    parquet = parquet_root(warehouse_dir).resolve()
    target = output_dir.resolve()
    if parquet not in target.parents:
        raise ValueError(f"Refuse to replace partition outside warehouse parquet root: {target}")
    if output_dir.exists():
        shutil.rmtree(output_dir)


def _write_symbol_parquet(
    frame: pd.DataFrame,
    table_name: str,
    *,
    symbol: str,
    warehouse_dir: Path | None,
) -> Path:
    output_dir = parquet_root(warehouse_dir) / table_name / "by_symbol"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{_safe_symbol(symbol)}.parquet"
    table_root = (parquet_root(warehouse_dir) / table_name).resolve()
    target = output_path.resolve()
    if table_root not in target.parents:
        raise ValueError(f"Refuse to write parquet outside table root: {target}")
    if output_path.exists():
        output_path.unlink()
    with duckdb.connect() as conn:
        conn.register("warehouse_frame", frame)
        conn.execute(f"COPY warehouse_frame TO '{_duckdb_path(output_path)}' (FORMAT PARQUET)")
    return output_path


def _write_run_parquet(
    frame: pd.DataFrame,
    table_name: str,
    *,
    run_id: str,
    warehouse_dir: Path | None,
) -> Path:
    output_dir = parquet_root(warehouse_dir) / table_name / "by_run"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{_safe_filename(run_id)}.parquet"
    table_root = (parquet_root(warehouse_dir) / table_name).resolve()
    target = output_path.resolve()
    if table_root not in target.parents:
        raise ValueError(f"Refuse to write parquet outside table root: {target}")
    if output_path.exists():
        output_path.unlink()
    with duckdb.connect() as conn:
        conn.register("warehouse_frame", frame)
        conn.execute(f"COPY warehouse_frame TO '{_duckdb_path(output_path)}' (FORMAT PARQUET)")
    return output_path


def _snapshot_dirs(root: Path, *, since: str | None, until: str | None) -> list[Path]:
    if not root.exists():
        return []
    since_ts = pd.Timestamp(since).normalize() if since else None
    until_ts = pd.Timestamp(until).normalize() if until else None
    output = []
    for path in sorted(root.iterdir()):
        if not path.is_dir():
            continue
        try:
            day = pd.Timestamp(path.name).normalize()
        except ValueError:
            continue
        if since_ts is not None and day < since_ts:
            continue
        if until_ts is not None and day > until_ts:
            continue
        output.append(path)
    return output


def _range_label(since: str | None, until: str | None) -> str:
    if since and until:
        return f"{since}..{until}"
    if since:
        return f"{since}.."
    if until:
        return f"..{until}"
    return "all"


def _resolve_symbols(
    *,
    symbols: list[str] | None,
    universe_file: Path | None,
    daily_root: Path,
) -> list[str]:
    if symbols:
        return sorted({_safe_symbol(symbol) for symbol in symbols})
    if universe_file and universe_file.exists():
        universe = pd.read_csv(universe_file, dtype={"symbol": str})
        if "symbol" in universe.columns:
            return sorted({_safe_symbol(symbol) for symbol in universe["symbol"].dropna().tolist()})
    if not daily_root.exists():
        return []
    return sorted({_safe_symbol(path.stem) for path in daily_root.glob("*.csv")})


def _daily_symbol_parquet_path(symbol: str, *, warehouse_dir: Path | None) -> Path:
    return parquet_root(warehouse_dir) / "daily_candles" / "by_symbol" / f"{_safe_symbol(symbol)}.parquet"


def _daily_candles_last_by_symbol(*, warehouse_dir: Path | None) -> dict[str, str]:
    db_path = warehouse_db_path(warehouse_dir)
    if not db_path.exists():
        return {}
    try:
        refresh_warehouse_views(warehouse_dir=warehouse_dir)
        with duckdb.connect(str(db_path), read_only=True) as conn:
            views = _warehouse_views(conn)
            if "daily_candles_index" in views and {"symbol", "last_timestamp", "status"}.issubset(
                _view_columns(conn, "daily_candles_index")
            ):
                rows = conn.execute(
                    """
                    SELECT symbol, MAX(last_timestamp)
                    FROM daily_candles_index
                    WHERE status IN ('synced', 'skipped') AND last_timestamp IS NOT NULL AND last_timestamp <> ''
                    GROUP BY symbol
                    """
                ).fetchall()
                return {_safe_symbol(row[0]): str(row[1]) for row in rows if row[1]}
            if "daily_candles" in views and {"symbol", "timestamp"}.issubset(_view_columns(conn, "daily_candles")):
                rows = conn.execute(
                    """
                    SELECT symbol, MAX(timestamp)
                    FROM daily_candles
                    GROUP BY symbol
                    """
                ).fetchall()
                return {_safe_symbol(row[0]): _clean_date(row[1]) for row in rows if row[1]}
    except Exception:
        return {}
    return {}


def _last_csv_timestamp(path: Path) -> pd.Timestamp | None:
    line = _last_nonempty_line(path)
    if not line:
        return None
    first = line.split(",", 1)[0].strip().strip('"')
    if first.lower() == "timestamp":
        return None
    value = pd.to_datetime(first, errors="coerce")
    if pd.isna(value):
        return None
    return pd.Timestamp(value).normalize()


def _last_nonempty_line(path: Path) -> str:
    with path.open("rb") as handle:
        handle.seek(0, 2)
        position = handle.tell()
        buffer = b""
        while position > 0:
            read_size = min(4096, position)
            position -= read_size
            handle.seek(position)
            buffer = handle.read(read_size) + buffer
            lines = buffer.splitlines()
            if len(lines) > 1:
                for raw in reversed(lines):
                    line = raw.decode("utf-8", errors="ignore").strip()
                    if line:
                        return line
        line = buffer.decode("utf-8", errors="ignore").strip()
        return line


def _daily_candle_index_row(
    run_id: str,
    target_date: str,
    symbol: str,
    path: Path,
    row_count: int,
    first_timestamp: str,
    last_timestamp: str,
    status: str,
    ingested_at: str,
) -> dict:
    return {
        "warehouse_run_id": run_id,
        "warehouse_target_date": target_date,
        "symbol": _safe_symbol(symbol),
        "source_path": str(path),
        "row_count": int(row_count),
        "first_timestamp": first_timestamp,
        "last_timestamp": last_timestamp,
        "status": status,
        "warehouse_ingested_at": ingested_at,
    }
