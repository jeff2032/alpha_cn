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

WAREHOUSE_TABLES = [
    *CSV_REPORT_SPECS.keys(),
    "report_index",
    *SNAPSHOT_CSV_SPECS.keys(),
    "snapshot_index",
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
        report_rows.append(
            _report_row(resolved_run_id, target_date, table_name, path, len(output), "ingested", ingested_at)
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
            row = _report_row(resolved_run_id, target_date, table_name, path, len(output), "ingested", ingested_at)
            snapshot_rows.append(row)
            all_rows.append(row)
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
