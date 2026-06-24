from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import sleep

import pandas as pd

from quant_a_stock.backtest.engine import run_backtest
from quant_a_stock.backtest.engine import summarize_equity_curve
from quant_a_stock.backtest.optimize import optimize_sma_trend_filter
from quant_a_stock.backtest.research_portfolio import ResearchPortfolioConfig
from quant_a_stock.backtest.research_portfolio import optimize_research_portfolio
from quant_a_stock.backtest.research_portfolio import run_research_portfolio_backtest
from quant_a_stock.backtest.report import save_report
from quant_a_stock.backtest.validate import validate_strategy
from quant_a_stock.cleaning.pipeline import clean_candles
from quant_a_stock.config import DEFAULT_PATHS
from quant_a_stock.data.akshare_client import fetch_daily
from quant_a_stock.data.cache import daily_cache_path, load_daily_cache, save_daily_cache
from quant_a_stock.data.calendar import resolve_cached_trading_date
from quant_a_stock.data_lifecycle import build_data_loop_status
from quant_a_stock.data_lifecycle import build_retention_plan
from quant_a_stock.data.universe import fetch_stock_universe
from quant_a_stock.data.universe import filter_universe
from quant_a_stock.data.universe import load_universe_file
from quant_a_stock.data.universe import save_universe_file
from quant_a_stock.research.candidates import ResearchCandidateConfig
from quant_a_stock.research.candidates import build_research_candidates
from quant_a_stock.research.candidates import fetch_company_profiles
from quant_a_stock.research.candidates import fetch_risk_notices
from quant_a_stock.research.candidates import load_cache_listing_info
from quant_a_stock.research.candidates import load_report
from quant_a_stock.research.lifecycle import build_candidate_lifecycle_tracking
from quant_a_stock.research.lifecycle import save_candidate_lifecycle_reports
from quant_a_stock.research.report import save_research_candidates_markdown
from quant_a_stock.research.review import build_research_review
from quant_a_stock.research.review import save_research_review_reports
from quant_a_stock.research.snapshot import save_research_snapshot
from quant_a_stock.research.summary import build_daily_research_summary
from quant_a_stock.research.summary import save_daily_research_summary_markdown
from quant_a_stock.screening.patterns import AccumulationSetupConfig
from quant_a_stock.screening.patterns import BaseBreakoutSetupConfig
from quant_a_stock.screening.patterns import TrendPullbackSetupConfig
from quant_a_stock.screening.patterns import scan_accumulation_setups
from quant_a_stock.screening.patterns import scan_base_breakout_setups
from quant_a_stock.screening.patterns import scan_trend_pullback_setups
from quant_a_stock.sentiment.report import save_market_theme_markdown
from quant_a_stock.sentiment.report import save_sentiment_markdown
from quant_a_stock.sentiment.score import SentimentConfig
from quant_a_stock.sentiment.score import build_market_theme
from quant_a_stock.sentiment.score import build_sentiment_scores
from quant_a_stock.sentiment.score import load_symbols_from_watchlist
from quant_a_stock.strategy.registry import available_strategy_names
from quant_a_stock.strategy.registry import generate_strategy_signals
from quant_a_stock.strategy.registry import get_strategy
from quant_a_stock.strategy.sma_trend_filter import STRATEGY_NAME
from quant_a_stock.warehouse import backfill_research_snapshots
from quant_a_stock.warehouse import ingest_latest_reports
from quant_a_stock.warehouse import sync_candidate_lifecycles_to_warehouse
from quant_a_stock.warehouse import sync_daily_candles_to_warehouse
from quant_a_stock.warehouse import sync_stock_universe_to_warehouse
from quant_a_stock.warehouse import warehouse_review as build_warehouse_review
from quant_a_stock.warehouse import warehouse_status as build_warehouse_status


def _parse_csv_ints(value: str) -> list[int]:
    return [int(part.strip()) for part in value.split(",") if part.strip()]


def _parse_csv_floats(value: str) -> list[float]:
    return [float(part.strip()) for part in value.split(",") if part.strip()]


def _parse_markets(values: list[str] | None) -> set[str] | None:
    if not values:
        return None
    return {value.lower() for value in values}


def _load_candles(symbols: list[str], *, since: str | None = None) -> dict[str, pd.DataFrame]:
    candles_by_symbol = {}
    for symbol in symbols:
        candles = load_daily_cache(symbol)
        candles = clean_candles(candles, symbol=symbol)
        if since:
            candles = candles[candles["timestamp"] >= pd.Timestamp(since)].reset_index(drop=True)
        candles_by_symbol[symbol] = candles
    return candles_by_symbol


def _load_available_candles(symbols: list[str]) -> dict[str, pd.DataFrame]:
    candles_by_symbol = {}
    failures = []
    for symbol in symbols:
        try:
            candles_by_symbol[symbol] = clean_candles(load_daily_cache(symbol), symbol=symbol)
        except Exception as exc:
            failures.append(f"{symbol}: {exc}")
    if failures:
        print(f"跳过 {len(failures)} 个无法读取的缓存标的。")
        for failure in failures[:10]:
            print(f"  {failure}")
        if len(failures) > 10:
            print(f"  还有 {len(failures) - 10} 个未展开。")
    return candles_by_symbol


def _cached_symbols() -> list[str]:
    cache_dir = DEFAULT_PATHS.data_cache / "akshare" / "daily"
    if not cache_dir.exists():
        return []
    return sorted(path.stem for path in cache_dir.glob("*.csv"))


def _latest_report(pattern: str) -> Path | None:
    reports_dir = DEFAULT_PATHS.reports
    if not reports_dir.exists():
        return None
    reports = sorted(reports_dir.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    return reports[0] if reports else None


def _report_path_arg(value: str | None, *, latest_pattern: str, missing_message: str) -> Path:
    if value:
        return Path(value)
    path = _latest_report(latest_pattern)
    if path is None:
        raise SystemExit(missing_message)
    return path


def _latest_scan_report() -> Path | None:
    reports_dir = DEFAULT_PATHS.reports
    if not reports_dir.exists():
        return None
    reports = []
    for pattern in (
        "scan_accumulation_setup_*.csv",
        "scan_base_breakout_setup_*.csv",
        "scan_trend_pullback_setup_*.csv",
    ):
        reports.extend(reports_dir.glob(pattern))
    reports = sorted(reports, key=lambda path: path.stat().st_mtime, reverse=True)
    return reports[0] if reports else None


def _latest_scan_reports() -> list[Path]:
    reports_dir = DEFAULT_PATHS.reports
    if not reports_dir.exists():
        return []
    paths = []
    for pattern in (
        "scan_base_breakout_setup_*.csv",
        "scan_accumulation_setup_*.csv",
        "scan_trend_pullback_setup_*.csv",
    ):
        matches = sorted(
            reports_dir.glob(pattern),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if matches:
            paths.append(matches[0])
    return paths


def _load_latest_scan_reports() -> tuple[pd.DataFrame, list[Path]]:
    paths = _latest_scan_reports()
    frames = []
    for path in paths:
        frame = load_report(path)
        frame["scan_source"] = path.stem
        frames.append(frame)

    if not frames:
        return pd.DataFrame(), []

    merged = pd.concat(frames, ignore_index=True, sort=False)
    if "score" in merged.columns:
        merged["score"] = pd.to_numeric(merged["score"], errors="coerce").fillna(0.0)
        merged = merged.sort_values("score", ascending=False)
    merged = merged.drop_duplicates(subset=["symbol"], keep="first").reset_index(drop=True)
    return merged, paths


def _balanced_scan_selection(frame: pd.DataFrame, top: int | None) -> pd.DataFrame:
    if top is None or top <= 0 or len(frame) <= top or "scan_source" not in frame.columns:
        return frame

    sources = [source for source in frame["scan_source"].dropna().astype(str).unique() if source]
    if len(sources) <= 1:
        return frame.head(top)

    quota = max(1, top // len(sources))
    selected = []
    used_symbols: set[str] = set()
    for source in sources:
        subset = frame[frame["scan_source"] == source]
        subset = subset[~subset["symbol"].isin(used_symbols)].head(quota)
        if subset.empty:
            continue
        selected.append(subset)
        used_symbols.update(subset["symbol"].astype(str).tolist())

    selected_count = sum(len(part) for part in selected)
    if selected_count < top:
        remaining = frame[~frame["symbol"].isin(used_symbols)].head(top - selected_count)
        if not remaining.empty:
            selected.append(remaining)

    if not selected:
        return frame.head(top)
    return pd.concat(selected, ignore_index=True, sort=False).head(top)


def _add_names_from_universe(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    if output.empty:
        if "name" not in output.columns:
            output["name"] = ""
        return output
    if "symbol" in output.columns:
        output["symbol"] = output["symbol"].astype(str).str.zfill(6)
    universe_path = DEFAULT_PATHS.root / "data" / "universe" / "a_stock.csv"
    if not universe_path.exists():
        if "name" not in output.columns:
            output["name"] = ""
        return output
    universe = load_universe_file(universe_path).loc[:, ["symbol", "name"]].copy()
    universe["symbol"] = universe["symbol"].astype(str).str.zfill(6)
    universe = universe.rename(columns={"name": "_universe_name"})
    output = output.merge(
        universe,
        on="symbol",
        how="left",
    )
    if "name" not in output.columns:
        output["name"] = output["_universe_name"].fillna("")
    else:
        current_name = output["name"].fillna("").astype(str)
        output["name"] = current_name.mask(
            current_name.str.strip().eq(""),
            output["_universe_name"].fillna(""),
        )
    output = output.drop(columns=["_universe_name"], errors="ignore")
    return output


def _latest_weekday(value: str | None = None) -> pd.Timestamp:
    day = pd.Timestamp(value).normalize() if value else pd.Timestamp.now().normalize()
    while day.weekday() >= 5:
        day -= pd.Timedelta(days=1)
    return day


def _resolve_trading_date(value: str | None = None) -> pd.Timestamp:
    return resolve_cached_trading_date(value, cache_dir=DEFAULT_PATHS.data_cache)


def _announce_trading_date_resolution(requested: str | None, resolved: pd.Timestamp) -> None:
    if not requested:
        return
    requested_date = pd.Timestamp(requested).normalize()
    if requested_date != resolved:
        print(
            f"目标日期 {requested_date.date().isoformat()} 不是本地缓存中的交易日，"
            f"已回退到 {resolved.date().isoformat()}。"
        )


def _cached_last_date(symbol: str) -> pd.Timestamp | None:
    cache_path = daily_cache_path(symbol)
    if not cache_path.exists():
        return None
    try:
        timestamps = pd.read_csv(cache_path, usecols=["timestamp"])["timestamp"]
    except Exception:
        return None
    dates = pd.to_datetime(timestamps, errors="coerce").dropna()
    if dates.empty:
        return None
    return dates.iloc[-1].normalize()


def _incremental_start_from_last(
    last_date: pd.Timestamp,
    *,
    since: str | None,
    lookback_days: int,
) -> str:
    start = last_date.normalize() - pd.Timedelta(days=max(0, lookback_days))
    if since:
        start = max(start, pd.Timestamp(since).normalize())
    return start.date().isoformat()


def _incremental_since(
    symbol: str,
    *,
    since: str | None,
    lookback_days: int,
) -> str | None:
    last_date = _cached_last_date(symbol)
    if last_date is None:
        return since

    return _incremental_start_from_last(
        last_date,
        since=since,
        lookback_days=lookback_days,
    )


def _merge_with_daily_cache(symbol: str, candles: pd.DataFrame) -> pd.DataFrame:
    try:
        cached = load_daily_cache(symbol)
    except FileNotFoundError:
        return candles

    merged = pd.concat([cached, candles], ignore_index=True)
    return clean_candles(merged, symbol=symbol)


def _strategy_params(args: argparse.Namespace) -> dict[str, int | float]:
    return {
        "fast_window": args.fast_window,
        "slow_window": args.slow_window,
        "trend_window": args.trend_window,
        "breakout_window": args.breakout_window,
        "exit_window": args.exit_window,
        "base_window": args.base_window,
        "volume_window": args.volume_window,
        "max_base_range": args.max_base_range,
        "proximity_pct": args.proximity_pct,
        "volume_ratio_min": args.volume_ratio_min,
        "max_ret_20": args.max_ret_20,
        "exit_ma_window": args.exit_ma_window,
        "ema_fast_window": args.ema_fast_window,
        "ema_slow_window": args.ema_slow_window,
        "rsi_window": args.rsi_window,
        "rsi_entry": args.rsi_entry,
        "rsi_exit": args.rsi_exit,
    }


def _require_strategy(name: str) -> None:
    try:
        get_strategy(name)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def _portfolio_metrics_from_curves(curves: list[pd.DataFrame]) -> dict[str, float | int | str]:
    returns = pd.concat(
        [
            curve.set_index("timestamp")["strategy_return"].rename(curve["symbol"].iloc[0])
            for curve in curves
        ],
        axis=1,
    ).fillna(0.0)
    exposures = pd.concat(
        [
            (curve.set_index("timestamp")["position"] > 0)
            .astype(float)
            .rename(curve["symbol"].iloc[0])
            for curve in curves
        ],
        axis=1,
    ).fillna(0.0)
    entries = pd.concat(
        [
            curve.set_index("timestamp")["entry_trade"].rename(curve["symbol"].iloc[0])
            for curve in curves
        ],
        axis=1,
    ).fillna(0.0)
    portfolio_return = returns.mean(axis=1)
    portfolio_curve = pd.DataFrame(
        {
            "timestamp": portfolio_return.index,
            "strategy_return": portfolio_return.values,
            "position": exposures.mean(axis=1).values,
        }
    )
    portfolio_curve["equity"] = (1 + portfolio_curve["strategy_return"]).cumprod()
    return summarize_equity_curve(
        portfolio_curve,
        symbol="PORTFOLIO",
        trades=int(entries.sum().sum()),
    )


def _run_strategy_rows(
    candles_by_symbol: dict[str, pd.DataFrame],
    *,
    strategy_name: str,
    strategy_params: dict[str, int | float],
) -> list[dict]:
    rows: list[dict] = []
    curves: list[pd.DataFrame] = []
    for symbol, candles in candles_by_symbol.items():
        signal = generate_strategy_signals(strategy_name, candles, **strategy_params)
        result = run_backtest(candles, signal, symbol=symbol)
        metrics = {"strategy": strategy_name, **result.metrics}
        rows.append(metrics)
        curve = result.equity_curve[
            ["timestamp", "strategy_return", "position", "entry_trade"]
        ].copy()
        curve["symbol"] = symbol
        curves.append(curve)

    if curves:
        rows.append({"strategy": strategy_name, **_portfolio_metrics_from_curves(curves)})
    return rows


def sync_daily(args: argparse.Namespace) -> None:
    DEFAULT_PATHS.ensure()
    failures: list[str] = []
    for symbol in args.symbols:
        try:
            since = (
                _incremental_since(
                    symbol,
                    since=args.since,
                    lookback_days=args.lookback_days,
                )
                if args.incremental
                else args.since
            )
            candles = fetch_daily(
                symbol,
                since=since,
                until=args.until,
                adjust=args.adjust,
                asset_type=args.asset_type,
                etf_provider=args.etf_provider,
                stock_provider=args.stock_provider,
                retries=args.retries,
                retry_wait=args.retry_wait,
            )
            if args.incremental:
                candles = _merge_with_daily_cache(symbol, candles)
            path = save_daily_cache(candles, symbol)
            prefix = "增量" if args.incremental else "全量"
            print(f"{symbol}: {prefix}保存 {len(candles)} 行 -> {path}")
        except Exception as exc:
            failures.append(symbol)
            print(f"{symbol}: 下载失败: {exc}")

    if failures:
        raise SystemExit(f"sync-daily 有标的下载失败: {', '.join(failures)}")


def list_stock_universe(args: argparse.Namespace) -> None:
    universe = fetch_stock_universe(args.provider)
    filtered = filter_universe(
        universe.frame,
        markets=_parse_markets(args.markets),
        exclude_st=not args.include_st,
    )
    if args.limit:
        filtered = filtered.head(args.limit)
    output_path = save_universe_file(filtered, path=Path(args.output))
    print(f"数据源: {universe.provider}")
    print(f"标的数量: {len(filtered)}")
    print(f"已保存: {output_path}")


def _symbols_from_batch_args(args: argparse.Namespace) -> pd.DataFrame:
    if args.symbols:
        return pd.DataFrame({"symbol": args.symbols, "name": ""})
    if args.universe_file:
        return load_universe_file(Path(args.universe_file))

    universe = fetch_stock_universe(args.provider)
    return universe.frame


def _sync_stock_universe_symbol(
    idx: int,
    total: int,
    row: dict[str, object],
    args: argparse.Namespace,
) -> tuple[int, dict[str, object], str]:
    symbol = str(row["symbol"])
    name_value = row.get("name", "")
    name = "" if pd.isna(name_value) else str(name_value)
    prefix_text = f"[{idx + 1}/{total}] {symbol} {name}".rstrip()
    cache_path = daily_cache_path(symbol)
    if args.skip_existing and cache_path.exists() and not args.incremental:
        return (
            idx,
            {"symbol": symbol, "name": name, "status": "已跳过", "rows": "", "error": ""},
            f"{prefix_text}: 已存在，跳过",
        )

    try:
        since = (
            _incremental_since(
                symbol,
                since=args.since,
                lookback_days=args.lookback_days,
            )
            if args.incremental
            else args.since
        )
        candles = fetch_daily(
            symbol,
            since=since,
            until=args.until,
            adjust=args.adjust,
            asset_type="stock",
            stock_provider=args.stock_provider,
            retries=args.retries,
            retry_wait=args.retry_wait,
        )
        if args.incremental:
            candles = _merge_with_daily_cache(symbol, candles)
        path = save_daily_cache(candles, symbol)
        status = "增量保存" if args.incremental else "已保存"
        result = {
            "symbol": symbol,
            "name": name,
            "status": status,
            "rows": len(candles),
            "error": "",
        }
        message = f"{prefix_text}: {status} {len(candles)} 行 -> {path}"
    except Exception as exc:
        result = {
            "symbol": symbol,
            "name": name,
            "status": "失败",
            "rows": 0,
            "error": str(exc),
        }
        message = f"{prefix_text}: 下载失败: {exc}"

    if args.sleep > 0:
        sleep(args.sleep)
    return idx, result, message


def sync_stock_universe(args: argparse.Namespace) -> None:
    DEFAULT_PATHS.ensure()
    universe = _symbols_from_batch_args(args)
    universe = filter_universe(
        universe,
        markets=_parse_markets(args.markets),
        exclude_st=not args.include_st,
    )
    if args.offset:
        universe = universe.iloc[args.offset :]
    if args.limit:
        universe = universe.head(args.limit)
    universe = universe.reset_index(drop=True)

    rows = []
    total = len(universe)
    tasks = [(idx, total, row.to_dict()) for idx, row in universe.iterrows()]
    workers = max(1, int(args.workers))
    if workers > 1 and total:
        print(f"并行下载: workers={workers}, sleep={args.sleep}, total={total}")
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(_sync_stock_universe_symbol, idx, total, row, args)
                for idx, total, row in tasks
            ]
            for completed, future in enumerate(as_completed(futures), start=1):
                idx, result, message = future.result()
                result["_order"] = idx
                rows.append(result)
                print(f"{message} (完成 {completed}/{total})")
    else:
        for idx, total, row in tasks:
            idx, result, message = _sync_stock_universe_symbol(idx, total, row, args)
            result["_order"] = idx
            rows.append(result)
            print(message)

    report_rows = [
        {key: value for key, value in row.items() if key != "_order"}
        for row in sorted(rows, key=lambda item: int(item["_order"]))
    ]
    report_path = save_report(report_rows, report_type="sync_stock_universe")
    summary = pd.DataFrame(report_rows)["status"].value_counts().to_dict() if report_rows else {}
    print(f"汇总: {summary}")
    print(f"报告: {report_path}")


def cache_status(args: argparse.Namespace) -> None:
    if args.symbols:
        universe = pd.DataFrame({"symbol": args.symbols, "name": ""})
        markets = None
    elif args.universe_file:
        universe = load_universe_file(Path(args.universe_file))
        markets = _parse_markets(args.markets)
    else:
        universe = pd.DataFrame({"symbol": _cached_symbols(), "name": ""})
        markets = _parse_markets(args.markets)

    universe = filter_universe(
        universe,
        markets=markets,
        exclude_st=not args.include_st,
    )
    rows = []
    for _, row in universe.iterrows():
        symbol = str(row["symbol"])
        cache_path = daily_cache_path(symbol)
        rows.append(
            {
                "symbol": symbol,
                "name": str(row.get("name", "")),
                "market": str(row.get("market", "")),
                "cached": cache_path.exists(),
                "path": str(cache_path),
            }
        )

    result = pd.DataFrame(rows)
    total = len(result)
    cached = int(result["cached"].sum()) if total else 0
    missing = total - cached
    pct = cached / total * 100 if total else 0.0

    print(f"总数: {total}")
    print(f"已缓存: {cached}")
    print(f"缺失: {missing}")
    print(f"完成比例: {pct:.2f}%")

    missing_rows = result[~result["cached"]] if total else result
    if args.output_missing:
        output_path = Path(args.output_missing)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        missing_rows[["symbol", "name", "market"]].to_csv(output_path, index=False)
        print(f"缺失清单已保存: {output_path}")

    if args.show_missing and not missing_rows.empty:
        print(missing_rows[["symbol", "name", "market"]].head(args.top).to_string(index=False))


def cache_date_status(args: argparse.Namespace) -> None:
    if args.symbols:
        universe = pd.DataFrame({"symbol": args.symbols, "name": ""})
        markets = None
    elif args.universe_file:
        universe = load_universe_file(Path(args.universe_file))
        markets = _parse_markets(args.markets)
    else:
        universe = pd.DataFrame({"symbol": _cached_symbols(), "name": ""})
        markets = _parse_markets(args.markets)

    universe = filter_universe(
        universe,
        markets=markets,
        exclude_st=not args.include_st,
    )
    if args.exact_target_date and args.target_date:
        target_date = pd.Timestamp(args.target_date).normalize()
    else:
        target_date = _resolve_trading_date(args.target_date)
        _announce_trading_date_resolution(args.target_date, target_date)

    rows = []
    for _, row in universe.iterrows():
        symbol = str(row["symbol"])
        cache_path = daily_cache_path(symbol)
        cached = cache_path.exists()
        first_date = None
        last_date = None
        row_count = 0

        if cached:
            try:
                timestamps = pd.read_csv(cache_path, usecols=["timestamp"])["timestamp"]
                dates = pd.to_datetime(timestamps, errors="coerce").dropna()
                row_count = len(dates)
                if row_count:
                    first_date = dates.iloc[0].normalize()
                    last_date = dates.iloc[-1].normalize()
            except Exception:
                cached = False

        stale = (last_date is None) or (last_date < target_date)
        rows.append(
            {
                "symbol": symbol,
                "name": str(row.get("name", "")),
                "market": str(row.get("market", "")),
                "cached": cached,
                "first": first_date.date().isoformat() if first_date is not None else "",
                "last": last_date.date().isoformat() if last_date is not None else "",
                "rows": row_count,
                "stale": stale,
                "path": str(cache_path),
            }
        )

    result = pd.DataFrame(rows)
    total = len(result)
    cached_count = int(result["cached"].sum()) if total else 0
    stale_count = int(result["stale"].sum()) if total else 0
    fresh_count = total - stale_count
    latest_last = result.loc[result["last"] != "", "last"].max() if total else ""
    earliest_last = result.loc[result["last"] != "", "last"].min() if total else ""

    print(f"目标日期: {target_date.date().isoformat()}")
    print(f"总数: {total}")
    print(f"已缓存: {cached_count}")
    print(f"已到目标日期: {fresh_count}")
    print(f"未到目标日期: {stale_count}")
    print(f"达标比例: {(fresh_count / total * 100 if total else 0):.2f}%")
    print(f"最早最后日期: {earliest_last}")
    print(f"最晚最后日期: {latest_last}")

    stale_rows = result[result["stale"]] if total else result
    if args.output_stale:
        output_path = Path(args.output_stale)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        stale_rows[["symbol", "name", "market", "first", "last", "rows"]].to_csv(
            output_path,
            index=False,
        )
        print(f"过期清单已保存: {output_path}")

    if args.show_stale and not stale_rows.empty:
        print(
            stale_rows[["symbol", "name", "market", "first", "last", "rows"]]
            .head(args.top)
            .to_string(index=False)
        )


def backtest(args: argparse.Namespace) -> None:
    _require_strategy(args.strategy)
    candles_by_symbol = _load_candles(args.symbols)
    rows = _run_strategy_rows(
        candles_by_symbol,
        strategy_name=args.strategy,
        strategy_params=_strategy_params(args),
    )

    report_path = save_report(rows, report_type="backtest")
    print(pd.DataFrame(rows).to_string(index=False))
    print(f"报告: {report_path}")


def optimize(args: argparse.Namespace) -> None:
    if args.strategy != STRATEGY_NAME:
        raise SystemExit(f"optimize 目前只支持 {STRATEGY_NAME}")
    candles_by_symbol = _load_candles(args.symbols)
    result = optimize_sma_trend_filter(
        candles_by_symbol,
        fast_windows=_parse_csv_ints(args.fast_windows),
        slow_windows=_parse_csv_ints(args.slow_windows),
        trend_windows=_parse_csv_ints(args.trend_windows),
    )
    rows = result.to_dict("records")
    report_path = save_report(rows, report_type="optimize")
    print(result.head(10).to_string(index=False))
    print(f"报告: {report_path}")


def validate(args: argparse.Namespace) -> None:
    _require_strategy(args.strategy)
    candles_by_symbol = _load_candles(args.symbols)
    result = validate_strategy(
        candles_by_symbol,
        strategy_name=args.strategy,
        strategy_params=_strategy_params(args),
        since=args.since,
    )
    rows = result.to_dict("records")
    report_path = save_report(rows, report_type="validate")
    print(result.to_string(index=False))
    print(f"报告: {report_path}")


def compare(args: argparse.Namespace) -> None:
    strategies = args.strategies or available_strategy_names()
    for strategy_name in strategies:
        _require_strategy(strategy_name)
    candles_by_symbol = _load_candles(args.symbols)

    rows = []
    for strategy_name in strategies:
        strategy_rows = _run_strategy_rows(
            candles_by_symbol,
            strategy_name=strategy_name,
            strategy_params=_strategy_params(args),
        )
        rows.extend(row for row in strategy_rows if row["symbol"] == "PORTFOLIO")

    result = pd.DataFrame(rows).sort_values(
        ["return_pct", "sharpe", "max_drawdown"],
        ascending=[False, False, False],
    )
    report_path = save_report(result.to_dict("records"), report_type="compare")
    print(result.to_string(index=False))
    print(f"报告: {report_path}")


def scan_pattern(args: argparse.Namespace) -> None:
    if args.pattern not in {"base_breakout_setup", "accumulation_setup", "trend_pullback_setup"}:
        raise SystemExit(
            "不支持的形态。目前可用: base_breakout_setup, accumulation_setup, trend_pullback_setup"
        )

    symbols = args.symbols or _cached_symbols()
    if not symbols:
        raise SystemExit("没有传入标的，也没有找到本地缓存 CSV。")

    candles_by_symbol = _load_candles(symbols)
    if args.pattern == "base_breakout_setup":
        config = BaseBreakoutSetupConfig(
            base_window=args.base_window,
            trend_window=args.trend_window,
            volume_window=args.volume_window,
            max_base_range=args.max_base_range,
            proximity_pct=args.proximity_pct,
            volume_ratio_min=args.volume_ratio_min,
            max_ret_20=args.max_ret_20,
        )
        result = scan_base_breakout_setups(
            candles_by_symbol,
            config=config,
            min_score=args.min_score,
            include_extended=args.include_extended,
            stages=set(args.stages) if args.stages else None,
            min_amount_ma20=args.min_amount_ma20,
            min_volume_ratio=args.min_volume_ratio,
            max_close_vs_trend=args.max_close_vs_trend,
            max_ret_20=args.filter_max_ret_20,
            require_positive_trend_slope=args.require_positive_trend_slope,
        )
        report_type = "scan_base_breakout_setup"
    elif args.pattern == "accumulation_setup":
        accumulation_min_volume_ratio = (
            args.min_volume_ratio if args.min_volume_ratio is not None else 1.05
        )
        accumulation_max_volume_ratio = (
            args.max_volume_ratio if args.max_volume_ratio is not None else 2.20
        )
        accumulation_max_close_vs_trend = (
            args.max_close_vs_trend if args.max_close_vs_trend is not None else 0.12
        )
        accumulation_min_close_vs_trend = (
            args.min_close_vs_trend if args.min_close_vs_trend is not None else -0.05
        )
        accumulation_max_ret_20 = args.filter_max_ret_20 if args.filter_max_ret_20 is not None else 0.15
        config = AccumulationSetupConfig(
            base_window=args.base_window,
            trend_window=args.trend_window,
            volume_window=args.volume_window,
            max_base_range=args.max_base_range,
            min_price_position=args.min_price_position,
            max_price_position=args.max_price_position,
            min_distance_to_high=args.min_distance_to_high,
            max_distance_to_high=args.max_distance_to_high,
            min_close_vs_trend=accumulation_min_close_vs_trend,
            max_close_vs_trend=accumulation_max_close_vs_trend,
            max_close_vs_cost=args.max_close_vs_cost,
            min_volume_ratio=accumulation_min_volume_ratio,
            max_volume_ratio=accumulation_max_volume_ratio,
            max_ret_20=accumulation_max_ret_20,
            max_ret_60=args.max_ret_60,
        )
        result = scan_accumulation_setups(
            candles_by_symbol,
            config=config,
            min_score=args.min_score,
            stages=set(args.stages) if args.stages else None,
            min_amount_ma20=args.min_amount_ma20,
            min_volume_ratio=args.min_volume_ratio,
            max_volume_ratio=accumulation_max_volume_ratio,
            max_close_vs_trend=args.max_close_vs_trend,
            max_close_vs_cost=args.max_close_vs_cost,
            max_ret_20=args.filter_max_ret_20,
            max_ret_60=args.max_ret_60,
            max_price_position=args.max_price_position,
            require_positive_trend_slope=args.require_positive_trend_slope,
        )
        report_type = "scan_accumulation_setup"
    else:
        trend_min_volume_ratio = args.min_volume_ratio if args.min_volume_ratio is not None else 0.65
        trend_max_volume_ratio = args.max_volume_ratio if args.max_volume_ratio is not None else 3.20
        trend_max_close_vs_trend = (
            args.max_close_vs_trend if args.max_close_vs_trend is not None else 0.65
        )
        trend_min_close_vs_trend = (
            args.min_close_vs_trend if args.min_close_vs_trend is not None else -0.08
        )
        trend_max_ret_20 = args.filter_max_ret_20 if args.filter_max_ret_20 is not None else 0.18
        trend_min_amount_ma20 = (
            args.min_amount_ma20 if args.min_amount_ma20 is not None else 100_000_000
        )
        config = TrendPullbackSetupConfig(
            trend_window=args.trend_window,
            fast_trend_window=args.fast_trend_window,
            pullback_window=args.pullback_window,
            volume_window=args.volume_window,
            min_ret_60=args.min_ret_60,
            max_ret_20=trend_max_ret_20,
            max_drawdown_from_high=args.max_drawdown_from_high,
            min_close_vs_trend=trend_min_close_vs_trend,
            max_close_vs_trend=trend_max_close_vs_trend,
            min_trend_slope_20=args.min_trend_slope_20,
            min_volume_ratio=trend_min_volume_ratio,
            max_volume_ratio=trend_max_volume_ratio,
            min_amount_ma20=trend_min_amount_ma20,
        )
        result = scan_trend_pullback_setups(
            candles_by_symbol,
            config=config,
            min_score=args.min_score,
            stages=set(args.stages) if args.stages else None,
            min_amount_ma20=trend_min_amount_ma20,
            min_volume_ratio=args.min_volume_ratio,
            min_ret_60=args.min_ret_60,
            max_ret_20=trend_max_ret_20,
            max_close_vs_trend=trend_max_close_vs_trend,
            max_drawdown_from_high=args.max_drawdown_from_high,
            max_volume_ratio=trend_max_volume_ratio,
        )
        report_type = "scan_trend_pullback_setup"
    report_path = save_report(result.to_dict("records"), report_type=report_type)
    if result.empty:
        print("没有找到符合条件的形态。")
    else:
        print(result.head(args.top).to_string(index=False))
    print(f"报告: {report_path}")


def _sentiment_watchlist_from_args(args: argparse.Namespace) -> pd.DataFrame:
    if args.symbols:
        frame = pd.DataFrame({"symbol": args.symbols, "name": ""})
    else:
        watchlist_path = Path(args.watchlist) if args.watchlist else None
        if args.latest_scan:
            frame, paths = _load_latest_scan_reports()
            if frame.empty:
                raise SystemExit("没有找到最新形态扫描报告，请先运行 scan-pattern。")
            print("使用最新形态扫描报告: " + "；".join(str(path) for path in paths))
            frame = _balanced_scan_selection(frame, args.top)
            return _add_names_from_universe(frame)
        if watchlist_path is None:
            raise SystemExit("请传入 --symbols、--watchlist，或使用 --latest-scan。")
        frame = load_symbols_from_watchlist(watchlist_path)

    if args.top and len(frame) > args.top:
        frame = frame.head(args.top)
    return _add_names_from_universe(frame)


def sentiment_score(args: argparse.Namespace) -> None:
    watchlist = _sentiment_watchlist_from_args(args)
    target_date = _resolve_trading_date(args.target_date).date().isoformat()
    _announce_trading_date_resolution(args.target_date, pd.Timestamp(target_date))
    scores, meta = build_sentiment_scores(
        watchlist,
        config=SentimentConfig(
            news_days=args.news_days,
            research_days=args.research_days,
            hot_rank_top=args.hot_rank_top,
            target_date=target_date,
        ),
    )
    csv_path = save_report(scores.to_dict("records"), report_type="sentiment_watchlist")
    md_path = save_sentiment_markdown(scores, meta)

    if scores.empty:
        print("没有可展示的情绪评分结果。")
    else:
        display = scores.head(args.display_top).rename(
            columns={
                "symbol": "代码",
                "name": "名称",
                "sentiment_score": "情绪分",
                "hot_rank": "人气排名",
                "news_count": "新闻数",
                "core_news_count": "核心新闻",
                "generic_news_count": "泛消息",
                "positive_hits": "正向命中",
                "risk_hits": "风险命中",
                "research_report_count": "研报数",
                "buy_rating_count": "买入研报",
                "top_keywords": "热门关键词",
            }
        )
        print(
            display[
                [
                    "代码",
                    "名称",
                    "情绪分",
                    "人气排名",
                    "核心新闻",
                    "泛消息",
                    "研报数",
                    "买入研报",
                    "风险命中",
                    "热门关键词",
                ]
            ].to_string(index=False)
        )
    print(f"CSV 报告: {csv_path}")
    print(f"中文报告: {md_path}")


def market_theme(args: argparse.Namespace) -> None:
    target_date = _resolve_trading_date(args.target_date).date().isoformat()
    _announce_trading_date_resolution(args.target_date, pd.Timestamp(target_date))
    theme, meta = build_market_theme(target_date)
    csv_path = save_report(theme.to_dict("records"), report_type="market_theme")
    md_path = save_market_theme_markdown(theme, meta)

    if theme.empty:
        print("没有可展示的市场主线结果。")
    else:
        display = theme.head(args.top).rename(
            columns={
                "theme": "方向",
                "theme_score": "主线分",
                "stock_count": "标的数",
                "limit_count": "涨停数",
                "strong_count": "强势数",
                "amount": "成交额",
            }
        )
        print(display[["方向", "主线分", "涨停数", "强势数", "标的数", "成交额"]].to_string(index=False))
    print(f"CSV 报告: {csv_path}")
    print(f"中文报告: {md_path}")


def research_candidates(args: argparse.Namespace) -> None:
    resolved_target = _resolve_trading_date(args.target_date)
    _announce_trading_date_resolution(args.target_date, resolved_target)
    target_date = resolved_target.date().isoformat()
    scan_paths: list[Path] = []
    if args.scan_report:
        scan_path = Path(args.scan_report)
        scan = load_report(scan_path)
        scan_paths = [scan_path]
    else:
        scan, scan_paths = _load_latest_scan_reports()
        if scan.empty:
            raise SystemExit("没有找到形态扫描报告，请先运行 scan-pattern。")
    sentiment_path = _report_path_arg(
        args.sentiment_report,
        latest_pattern="sentiment_watchlist_*.csv",
        missing_message="没有找到情绪评分报告，请先运行 sentiment-score。",
    )
    theme_path: Path | None = None
    theme = pd.DataFrame()
    if args.refresh_theme:
        theme, theme_meta = build_market_theme(target_date)
        theme_path = save_report(theme.to_dict("records"), report_type="market_theme")
        save_market_theme_markdown(theme, theme_meta)
    else:
        theme_path = _latest_report("market_theme_*.csv")
        if theme_path is not None:
            theme = pd.read_csv(theme_path)

    sentiment = load_report(sentiment_path)
    symbols = scan["symbol"].tolist()

    errors: list[str] = []
    cache_info = load_cache_listing_info(symbols, target_date=target_date)
    profiles = pd.DataFrame()
    risk_notices = pd.DataFrame()
    if args.fetch_profiles:
        profiles, profile_errors = fetch_company_profiles(symbols)
        errors.extend(profile_errors)
    if args.fetch_notices:
        start_date = (
            pd.Timestamp(target_date).normalize() - pd.Timedelta(days=args.risk_days)
        ).date().isoformat()
        risk_notices, notice_errors = fetch_risk_notices(
            symbols,
            start_date=start_date,
            end_date=target_date,
        )
        errors.extend(notice_errors)

    candidates = build_research_candidates(
        scan,
        sentiment,
        theme=theme,
        profiles=profiles,
        cache_info=cache_info,
        risk_notices=risk_notices,
        target_date=target_date,
        config=ResearchCandidateConfig(),
    )
    candidates = _add_names_from_universe(candidates)
    csv_path = save_report(candidates.to_dict("records"), report_type="research_candidates")
    md_path = save_research_candidates_markdown(
        candidates,
        meta={
            "target_date": target_date,
            "scan_report": "；".join(str(path) for path in scan_paths),
            "sentiment_report": str(sentiment_path),
            "theme_report": str(theme_path or ""),
            "errors": errors,
        },
    )

    if candidates.empty:
        print("没有可展示的研究候选。")
    else:
        display = candidates.head(args.top).rename(
            columns={
                "symbol": "代码",
                "name": "名称",
                "research_tier": "分层",
                "research_score": "研究分",
                "setup_phase": "节奏",
                "score": "形态分",
                "sentiment_score": "情绪分",
                "matched_theme": "主线",
                "co_rise_count": "同涨数",
                "total_penalty": "扣分",
            }
        )
        cols = ["代码", "名称", "分层", "研究分", "节奏", "形态分", "情绪分", "主线", "同涨数", "扣分"]
        print(display[[column for column in cols if column in display.columns]].to_string(index=False))
    print(f"CSV 报告: {csv_path}")
    print(f"中文报告: {md_path}")


def _research_backtest_symbols(args: argparse.Namespace) -> list[str]:
    if args.symbols:
        return args.symbols
    universe_path = Path(args.universe_file) if args.universe_file else DEFAULT_PATHS.root / "data" / "universe" / "a_stock.csv"
    if universe_path.exists():
        universe = load_universe_file(universe_path)
        universe = filter_universe(
            universe,
            markets=_parse_markets(args.markets),
            exclude_st=not args.include_st,
        )
        return universe["symbol"].tolist()
    return _cached_symbols()


def _research_time_window(args: argparse.Namespace, symbols: list[str]) -> tuple[str, str]:
    until = args.until
    if until is None:
        latest_dates = []
        for symbol in symbols:
            try:
                candles = load_daily_cache(symbol)
                latest_dates.append(pd.to_datetime(candles["timestamp"]).max())
            except Exception:
                continue
        if not latest_dates:
            raise SystemExit("无法从缓存推断结束日期。")
        until = max(latest_dates).date().isoformat()

    since = args.since
    if since is None:
        since = (pd.Timestamp(until).normalize() - pd.DateOffset(years=args.years)).date().isoformat()
    return since, until


def research_backtest(args: argparse.Namespace) -> None:
    symbols = _research_backtest_symbols(args)
    if args.limit:
        symbols = symbols[: args.limit]
    if not symbols:
        raise SystemExit("没有可回测的标的。")

    since, until = _research_time_window(args, symbols)

    print(f"回测标的数: {len(symbols)}")
    print(f"回测区间: {since} -> {until}")
    print("说明: 当前为技术代理版，仅回测形态/量价筛选，不使用历史情绪和历史主线，避免未来函数。")

    candles_by_symbol = _load_available_candles(symbols)
    result = run_research_portfolio_backtest(
        candles_by_symbol,
        since=since,
        until=until,
        portfolio_config=ResearchPortfolioConfig(
            top_n=args.top_n,
            min_score=args.min_score,
            min_amount_ma20=args.min_amount_ma20,
            min_volume_ratio=args.min_volume_ratio,
            max_close_vs_trend=args.max_close_vs_trend,
            max_ret_20=args.filter_max_ret_20,
            require_positive_trend_slope=args.require_positive_trend_slope,
            rebalance_frequency=args.rebalance_frequency,
            allow_stages=tuple(args.stages),
        ),
    )

    metrics = {"strategy": "research_candidates_technical_proxy", **result.metrics}
    metrics_path = save_report([metrics], report_type="research_backtest")
    yearly_path = save_report(result.yearly.to_dict("records"), report_type="research_backtest_yearly")
    holdings_path = save_report(result.holdings.to_dict("records"), report_type="research_backtest_holdings")
    candidates_path = save_report(result.candidates.to_dict("records"), report_type="research_backtest_candidates")

    print(pd.DataFrame([metrics]).to_string(index=False))
    if not result.yearly.empty:
        print(result.yearly.to_string(index=False))
    print(f"总体报告: {metrics_path}")
    print(f"年度报告: {yearly_path}")
    print(f"持仓明细: {holdings_path}")
    print(f"候选明细: {candidates_path}")


def research_optimize(args: argparse.Namespace) -> None:
    symbols = _research_backtest_symbols(args)
    if args.limit:
        symbols = symbols[: args.limit]
    if not symbols:
        raise SystemExit("没有可优化的标的。")

    since, until = _research_time_window(args, symbols)
    print(f"优化标的数: {len(symbols)}")
    print(f"优化区间: {since} -> {until}")
    print("说明: 当前为技术代理版参数扫描，不使用历史情绪和历史主线。")

    candles_by_symbol = _load_available_candles(symbols)
    result = optimize_research_portfolio(
        candles_by_symbol,
        since=since,
        until=until,
        top_ns=_parse_csv_ints(args.top_ns),
        min_scores=_parse_csv_floats(args.min_scores),
        max_ret_20s=_parse_csv_floats(args.max_ret_20s),
        rebalance_frequencies=args.rebalance_frequencies,
        min_amount_ma20=args.min_amount_ma20,
        min_volume_ratio=args.min_volume_ratio,
        max_close_vs_trend=args.max_close_vs_trend,
        require_positive_trend_slope=args.require_positive_trend_slope,
        allow_stages=tuple(args.stages),
    )
    report_path = save_report(result.to_dict("records"), report_type="research_optimize")

    if result.empty:
        print("没有可展示的优化结果。")
    else:
        print(result.head(args.display_top).to_string(index=False))
    print(f"优化报告: {report_path}")


def snapshot_research(args: argparse.Namespace) -> None:
    resolved_target = _resolve_trading_date(args.target_date)
    _announce_trading_date_resolution(args.target_date, resolved_target)
    target_date = resolved_target.date().isoformat()
    reports = {
        "scan_base_breakout_setup": Path(args.scan_report)
        if args.scan_report
        else _latest_report("scan_base_breakout_setup_*.csv"),
        "scan_accumulation_setup": _latest_report("scan_accumulation_setup_*.csv"),
        "scan_trend_pullback_setup": _latest_report("scan_trend_pullback_setup_*.csv"),
        "sentiment_watchlist": Path(args.sentiment_report)
        if args.sentiment_report
        else _latest_report("sentiment_watchlist_*.csv"),
        "market_theme": Path(args.theme_report)
        if args.theme_report
        else _latest_report("market_theme_*.csv"),
        "research_candidates": Path(args.research_report)
        if args.research_report
        else _latest_report("research_candidates_*.csv"),
    }
    snapshot_dir = save_research_snapshot(target_date=target_date, reports=reports)
    print(f"研究快照目录: {snapshot_dir}")
    for name, path in reports.items():
        print(f"{name}: {path or '未找到'}")


def daily_research_summary(args: argparse.Namespace) -> None:
    resolved_target = _resolve_trading_date(args.target_date)
    _announce_trading_date_resolution(args.target_date, resolved_target)
    target_date = resolved_target.date().isoformat()
    snapshot_dir = Path(args.snapshot_dir) if args.snapshot_dir else None
    summary = build_daily_research_summary(
        target_date=target_date,
        snapshot_dir=snapshot_dir,
    )
    csv_path = save_report(
        summary.candidates.to_dict("records"),
        report_type="daily_research_candidates",
    )
    md_path = save_daily_research_summary_markdown(summary, top=args.top)

    print(f"市场温度: {summary.market['regime']} ({summary.market['score']})")
    print(f"操作口径: {summary.market['advice']}")
    display = summary.candidates.head(args.top).rename(
        columns={
            "symbol": "代码",
            "name": "名称",
            "research_tier": "分层",
            "research_score": "研究分",
            "theme_cluster": "主题簇",
            "stage": "阶段",
            "setup_phase": "节奏",
            "core_news_count": "核心新闻",
            "research_report_count": "研报数",
            "total_penalty": "扣分",
        }
    )
    columns = ["代码", "名称", "分层", "研究分", "主题簇", "阶段", "节奏", "核心新闻", "研报数", "扣分"]
    print(display[[column for column in columns if column in display.columns]].to_string(index=False))
    print(f"候选 CSV: {csv_path}")
    print(f"中文复盘报告: {md_path}")


def research_review(args: argparse.Namespace) -> None:
    review = build_research_review(
        since=args.since,
        until=args.until,
        top_movers=args.top_movers,
        universe_file=Path(args.universe_file) if args.universe_file else None,
    )
    md_path, details_path, summary_path = save_research_review_reports(review)

    print(f"可用快照: {', '.join(review.snapshot_dates) or '无'}")
    print(f"已闭环信号日: {', '.join(review.closed_signal_dates) or '无'}")
    if review.by_tier.empty:
        print("没有可展示的复盘结果。")
    else:
        display = review.by_tier.rename(
            columns={
                "tier": "分层",
                "count": "样本",
                "avg_ret": "均值",
                "median_ret": "中位数",
                "win_rate": "胜率",
                "gt5_rate": "涨超5%",
                "lt_minus5_rate": "跌超5%",
            }
        )
        print(display[["分层", "样本", "均值", "中位数", "胜率", "涨超5%", "跌超5%"]].to_string(index=False))
    if not review.by_tier_horizon.empty:
        horizon_display = review.by_tier_horizon[
            review.by_tier_horizon["tier"].isin(["A1", "A2", "A3", "B1", "B2"])
        ].rename(
            columns={
                "tier": "分层",
                "horizon": "周期",
                "count": "样本",
                "avg_ret": "均值",
                "median_ret": "中位数",
                "win_rate": "胜率",
                "gt5_rate": "涨超5%",
                "lt_minus5_rate": "跌超5%",
            }
        )
        print("分层多周期表现:")
        print(
            horizon_display[["分层", "周期", "样本", "均值", "中位数", "胜率", "涨超5%", "跌超5%"]].to_string(
                index=False
            )
        )
    print(f"复盘报告: {md_path}")
    print(f"明细 CSV: {details_path}")
    print(f"汇总 CSV: {summary_path}")


def track_candidates(args: argparse.Namespace) -> None:
    resolved_until = _resolve_trading_date(args.until) if args.until else None
    if args.until and resolved_until is not None:
        _announce_trading_date_resolution(args.until, resolved_until)
    until = resolved_until.date().isoformat() if resolved_until is not None else None
    tracking_kwargs = {}
    if args.snapshot_root:
        tracking_kwargs["snapshot_root"] = Path(args.snapshot_root)
    if args.cache_dir:
        tracking_kwargs["cache_dir"] = Path(args.cache_dir)
    if args.universe_file:
        tracking_kwargs["universe_file"] = Path(args.universe_file)
    tracking = build_candidate_lifecycle_tracking(
        since=args.since,
        until=until,
        strategy_version=args.strategy_version,
        gap_trade_days=args.gap_trade_days,
        **tracking_kwargs,
    )
    lifecycle_path, daily_path, md_path = save_candidate_lifecycle_reports(tracking, top=args.top)
    print(f"生命周期目标日期: {tracking.target_date or '无'}")
    print(f"生命周期数量: {len(tracking.lifecycles)}")
    print(f"每日状态数量: {len(tracking.daily)}")
    print(f"生命周期 CSV: {lifecycle_path}")
    print(f"每日状态 CSV: {daily_path}")
    print(f"中文跟踪报告: {md_path}")
    if not tracking.summary.empty:
        display = tracking.summary.rename(
            columns={
                "first_action_bucket": "入池分组",
                "count": "样本",
                "active_count": "仍跟踪",
                "hit_count": "命中",
                "strong_hit_count": "强命中",
                "failed_count": "失败",
                "avg_ret_3d": "3日均值",
                "avg_ret_5d": "5日均值",
                "avg_ret_10d": "10日均值",
                "avg_high_5d": "5日最大浮盈",
                "avg_low_5d": "5日最大回撤",
            }
        )
        print("分组生命周期表现:")
        print(display.to_string(index=False))
    if args.write_warehouse:
        result = sync_candidate_lifecycles_to_warehouse(
            lifecycles=tracking.lifecycles,
            daily=tracking.daily,
            target_date=tracking.target_date,
            warehouse_dir=Path(args.warehouse_dir) if args.warehouse_dir else None,
            run_id=args.run_id,
        )
        print(f"已写入仓库: {result.db_path}")

def warehouse_ingest(args: argparse.Namespace) -> None:
    resolved_target_date = _resolve_trading_date(args.target_date)
    _announce_trading_date_resolution(args.target_date, resolved_target_date)
    target_date = resolved_target_date.date().isoformat()
    result = ingest_latest_reports(
        target_date=target_date,
        reports_dir=Path(args.reports_dir) if args.reports_dir else None,
        warehouse_dir=Path(args.warehouse_dir) if args.warehouse_dir else None,
        run_id=args.run_id,
    )
    print(f"研究仓库运行 ID: {result.run_id}")
    print(f"目标交易日: {result.target_date}")
    print(f"DuckDB: {result.db_path}")
    print(f"Parquet: {result.parquet_root}")
    if result.ingested.empty:
        print("没有入库记录。")
    else:
        display = result.ingested.rename(
            columns={
                "report_type": "报告类型",
                "status": "状态",
                "row_count": "行数",
                "source_path": "来源",
            }
        )
        print(display[["报告类型", "状态", "行数", "来源"]].to_string(index=False))
    if not result.status.empty:
        print("仓库状态:")
        print(result.status.to_string(index=False))


def warehouse_status(args: argparse.Namespace) -> None:
    status = build_warehouse_status(
        warehouse_dir=Path(args.warehouse_dir) if args.warehouse_dir else None,
    )
    if status.empty:
        print("研究仓库还没有初始化。")
        return
    print(status.to_string(index=False))


def data_loop_status(args: argparse.Namespace) -> None:
    target_date = None
    if args.target_date:
        resolved_target_date = _resolve_trading_date(args.target_date)
        _announce_trading_date_resolution(args.target_date, resolved_target_date)
        target_date = resolved_target_date.date().isoformat()
    layers, checks = build_data_loop_status(
        target_date=target_date,
        plan_date=args.plan_date,
        warehouse_dir=Path(args.warehouse_dir) if args.warehouse_dir else None,
        obsidian_root=Path(args.obsidian_root) if args.obsidian_root else None,
    )
    print("数据层状态:")
    display_layers = layers.rename(
        columns={
            "layer": "层",
            "role": "角色",
            "path": "路径",
            "exists": "存在",
            "files": "文件数",
            "mb": "MB",
            "newest": "最新修改",
            "retention_policy": "保留策略",
            "note": "说明",
        }
    )
    print(display_layers[["层", "角色", "存在", "文件数", "MB", "最新修改", "保留策略"]].to_string(index=False))
    print("")
    print("闭环检查:")
    display_checks = checks.rename(
        columns={
            "check": "检查项",
            "status": "状态",
            "detail": "说明",
            "target_date": "目标日",
        }
    )
    print(display_checks[["检查项", "状态", "目标日", "说明"]].to_string(index=False))


def data_retention_plan(args: argparse.Namespace) -> None:
    plan = build_retention_plan(
        reports_days=args.reports_days,
        ops_reports_days=args.ops_reports_days,
        logs_days=args.logs_days,
        snapshots_days=args.snapshots_days,
    )
    print("数据保留/清理预案（dry-run，不会删除文件）:")
    if plan.empty:
        print("没有命中可清理项。")
        return
    display = plan.rename(
        columns={
            "action": "动作",
            "layer": "层",
            "path": "路径",
            "files": "文件数",
            "mb": "MB",
            "last_modified": "最后修改",
            "reason": "原因",
        }
    )
    summary = display.groupby(["层", "动作"], dropna=False).agg({"文件数": "sum", "MB": "sum"}).reset_index()
    print("汇总:")
    print(summary.to_string(index=False))
    print("")
    print("明细:")
    print(display.head(args.top).to_string(index=False))
    if len(display) > args.top:
        print(f"还有 {len(display) - args.top} 项未展开。")


def warehouse_backfill_snapshots(args: argparse.Namespace) -> None:
    result = backfill_research_snapshots(
        snapshot_root=Path(args.snapshot_root) if args.snapshot_root else None,
        warehouse_dir=Path(args.warehouse_dir) if args.warehouse_dir else None,
        since=args.since,
        until=args.until,
        run_id=args.run_id,
    )
    print(f"快照回填运行 ID: {result.run_id}")
    print(f"日期范围: {result.target_date}")
    print(f"DuckDB: {result.db_path}")
    print(f"Parquet: {result.parquet_root}")
    if result.ingested.empty:
        print("没有找到可回填的研究快照。")
    else:
        display = result.ingested.rename(
            columns={
                "warehouse_target_date": "日期",
                "report_type": "表",
                "status": "状态",
                "row_count": "行数",
                "source_path": "来源",
            }
        )
        print(display[["日期", "表", "状态", "行数", "来源"]].head(args.display_top).to_string(index=False))
    if not result.status.empty:
        print("仓库状态:")
        print(result.status.to_string(index=False))


def warehouse_sync_universe(args: argparse.Namespace) -> None:
    resolved_target_date = _resolve_trading_date(args.target_date)
    _announce_trading_date_resolution(args.target_date, resolved_target_date)
    target_date = resolved_target_date.date().isoformat()
    result = sync_stock_universe_to_warehouse(
        universe_file=Path(args.universe_file),
        target_date=target_date,
        warehouse_dir=Path(args.warehouse_dir) if args.warehouse_dir else None,
        run_id=args.run_id,
    )
    print(f"股票池入库运行 ID: {result.run_id}")
    print(f"目标交易日: {result.target_date}")
    print(result.ingested.to_string(index=False))
    if not result.status.empty:
        print("仓库状态:")
        print(result.status.to_string(index=False))


def warehouse_sync_candles(args: argparse.Namespace) -> None:
    resolved_target_date = _resolve_trading_date(args.target_date)
    _announce_trading_date_resolution(args.target_date, resolved_target_date)
    target_date = resolved_target_date.date().isoformat()
    result = sync_daily_candles_to_warehouse(
        symbols=args.symbols,
        universe_file=Path(args.universe_file) if args.universe_file else None,
        cache_dir=Path(args.cache_dir) if args.cache_dir else None,
        source=args.source,
        since=args.since,
        until=args.until,
        target_date=target_date,
        warehouse_dir=Path(args.warehouse_dir) if args.warehouse_dir else None,
        run_id=args.run_id,
        limit=args.limit,
        force=args.force,
    )
    print(f"行情入库运行 ID: {result.run_id}")
    print(f"目标交易日: {result.target_date}")
    if result.ingested.empty:
        print("没有找到可同步的行情缓存。")
    else:
        summary = result.ingested.groupby("status").size().reset_index(name="count")
        print("同步结果:")
        print(summary.to_string(index=False))
        display = result.ingested.rename(
            columns={
                "symbol": "代码",
                "status": "状态",
                "row_count": "行数",
                "first_timestamp": "开始",
                "last_timestamp": "结束",
            }
        )
        print(display[["代码", "状态", "行数", "开始", "结束"]].head(args.display_top).to_string(index=False))
    if not result.status.empty:
        print("仓库状态:")
        print(result.status.to_string(index=False))


def warehouse_review(args: argparse.Namespace) -> None:
    review = build_warehouse_review(
        since=args.since,
        until=args.until,
        warehouse_dir=Path(args.warehouse_dir) if args.warehouse_dir else None,
    )
    tier = review["tier"]
    bucket = review.get("bucket", pd.DataFrame())
    miss_risk = review["miss_risk"]
    reports = review["reports"]
    if tier.empty and bucket.empty and miss_risk.empty and reports.empty:
        print("研究仓库还没有可复盘的数据。")
        return
    if not bucket.empty:
        print("模型桶表现:")
        print(bucket.to_string(index=False))
    if not tier.empty:
        print("分层表现:")
        print(tier.to_string(index=False))
    if not miss_risk.empty:
        print("错过样本风险归因:")
        print(miss_risk.to_string(index=False))
    if not reports.empty:
        print("报告索引:")
        print(reports.head(30).to_string(index=False))


def _add_strategy_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--fast-window", type=int, default=20)
    parser.add_argument("--slow-window", type=int, default=60)
    parser.add_argument("--trend-window", type=int, default=120)
    parser.add_argument("--breakout-window", type=int, default=55)
    parser.add_argument("--exit-window", type=int, default=20)
    parser.add_argument("--base-window", type=int, default=120)
    parser.add_argument("--volume-window", type=int, default=20)
    parser.add_argument("--max-base-range", type=float, default=0.65)
    parser.add_argument("--proximity-pct", type=float, default=0.05)
    parser.add_argument("--volume-ratio-min", type=float, default=1.3)
    parser.add_argument("--max-ret-20", type=float, default=0.35)
    parser.add_argument("--exit-ma-window", type=int, default=60)
    parser.add_argument("--ema-fast-window", type=int, default=20)
    parser.add_argument("--ema-slow-window", type=int, default=60)
    parser.add_argument("--rsi-window", type=int, default=14)
    parser.add_argument("--rsi-entry", type=float, default=35.0)
    parser.add_argument("--rsi-exit", type=float, default=55.0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quant_a_stock")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync = subparsers.add_parser("sync-daily", help="下载并缓存 AKShare 日线数据")
    sync.add_argument("--symbols", nargs="+", required=True)
    sync.add_argument("--since", default=None)
    sync.add_argument("--until", default=None)
    sync.add_argument("--adjust", default="qfq")
    sync.add_argument("--asset-type", choices=["auto", "etf", "stock"], default="auto")
    sync.add_argument("--etf-provider", choices=["eastmoney", "sina"], default="eastmoney")
    sync.add_argument("--stock-provider", choices=["eastmoney", "sina"], default="eastmoney")
    sync.add_argument("--incremental", action="store_true", help="基于本地缓存增量补数")
    sync.add_argument("--lookback-days", type=int, default=60, help="增量补数时向前回看的自然日")
    sync.add_argument("--retries", type=int, default=3)
    sync.add_argument("--retry-wait", type=float, default=1.0)
    sync.set_defaults(func=sync_daily)

    universe = subparsers.add_parser("list-stock-universe", help="获取并保存 A 股股票池")
    universe.add_argument("--provider", choices=["auto", "eastmoney", "exchange", "sina"], default="auto")
    universe.add_argument("--markets", nargs="+", default=["sh", "sz"])
    universe.add_argument("--include-st", action="store_true")
    universe.add_argument("--limit", type=int, default=None)
    universe.add_argument("--output", default="data/universe/a_stock.csv")
    universe.set_defaults(func=list_stock_universe)

    sync_universe = subparsers.add_parser(
        "sync-stock-universe",
        help="批量下载股票日线数据，支持断点续跑",
    )
    sync_universe.add_argument("--provider", choices=["auto", "eastmoney", "exchange", "sina"], default="auto")
    sync_universe.add_argument("--universe-file", default=None)
    sync_universe.add_argument("--symbols", nargs="+", default=None)
    sync_universe.add_argument("--markets", nargs="+", default=["sh", "sz"])
    sync_universe.add_argument("--include-st", action="store_true")
    sync_universe.add_argument("--since", default="2020-01-01")
    sync_universe.add_argument("--until", default=None)
    sync_universe.add_argument("--adjust", default="qfq")
    sync_universe.add_argument("--stock-provider", choices=["eastmoney", "sina"], default="sina")
    sync_universe.add_argument("--limit", type=int, default=None)
    sync_universe.add_argument("--offset", type=int, default=0)
    sync_universe.add_argument("--sleep", type=float, default=1.0)
    sync_universe.add_argument("--workers", type=int, default=1, help="并行下载线程数，默认 1 表示顺序下载")
    sync_universe.add_argument("--incremental", action="store_true", help="基于本地缓存增量补数")
    sync_universe.add_argument("--lookback-days", type=int, default=60, help="增量补数时向前回看的自然日")
    sync_universe.add_argument(
        "--skip-existing",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    sync_universe.add_argument("--retries", type=int, default=2)
    sync_universe.add_argument("--retry-wait", type=float, default=1.0)
    sync_universe.set_defaults(func=sync_stock_universe)

    status = subparsers.add_parser("cache-status", help="查看日线缓存缺失情况")
    status.add_argument("--universe-file", default=None)
    status.add_argument("--symbols", nargs="+", default=None)
    status.add_argument("--markets", nargs="+", default=["sh", "sz"])
    status.add_argument("--include-st", action="store_true")
    status.add_argument("--show-missing", action="store_true")
    status.add_argument("--top", type=int, default=20)
    status.add_argument("--output-missing", default=None)
    status.set_defaults(func=cache_status)

    date_status = subparsers.add_parser(
        "cache-date-status",
        help="查看缓存起止日期和未更新标的",
    )
    date_status.add_argument("--universe-file", default=None)
    date_status.add_argument("--symbols", nargs="+", default=None)
    date_status.add_argument("--markets", nargs="+", default=["sh", "sz"])
    date_status.add_argument("--include-st", action="store_true")
    date_status.add_argument("--target-date", default=None)
    date_status.add_argument("--show-stale", action="store_true")
    date_status.add_argument("--top", type=int, default=20)
    date_status.add_argument("--output-stale", default=None)
    date_status.add_argument(
        "--exact-target-date",
        action="store_true",
        help="按传入目标日精确检查，不回退到本地最近缓存交易日；数据同步流程使用",
    )
    date_status.set_defaults(func=cache_date_status)

    bt = subparsers.add_parser("backtest", help="使用缓存数据运行回测")
    bt.add_argument("--from-cache", action="store_true", help="从本地缓存读取数据")
    bt.add_argument("--strategy", default=STRATEGY_NAME)
    bt.add_argument("--symbols", nargs="+", required=True)
    bt.add_argument("--timeframe", default="1d")
    _add_strategy_arguments(bt)
    bt.set_defaults(func=backtest)

    opt = subparsers.add_parser("optimize", help="扫描 SMA 趋势策略参数")
    opt.add_argument("--strategy", default=STRATEGY_NAME)
    opt.add_argument("--symbols", nargs="+", required=True)
    opt.add_argument("--fast-windows", required=True)
    opt.add_argument("--slow-windows", required=True)
    opt.add_argument("--trend-windows", required=True)
    opt.set_defaults(func=optimize)

    val = subparsers.add_parser("validate", help="按年份和标的验证策略")
    val.add_argument("--strategy", default=STRATEGY_NAME)
    val.add_argument("--symbols", nargs="+", required=True)
    val.add_argument("--since", default=None)
    _add_strategy_arguments(val)
    val.set_defaults(func=validate)

    cmp_parser = subparsers.add_parser("compare", help="比较已注册策略")
    cmp_parser.add_argument("--strategies", nargs="+", default=None)
    cmp_parser.add_argument("--symbols", nargs="+", required=True)
    _add_strategy_arguments(cmp_parser)
    cmp_parser.set_defaults(func=compare)

    scan = subparsers.add_parser("scan-pattern", help="扫描缓存标的的形态")
    scan.add_argument("--pattern", default="base_breakout_setup")
    scan.add_argument("--symbols", nargs="+", default=None)
    scan.add_argument("--top", type=int, default=20)
    scan.add_argument("--min-score", type=float, default=50.0)
    scan.add_argument("--include-extended", action="store_true")
    scan.add_argument(
        "--stages",
        nargs="+",
        choices=[
            "watch",
            "near_breakout",
            "breakout",
            "extended",
            "accumulation",
            "pre_breakout",
            "overheated",
            "trend_pullback",
            "trend_resume",
        ],
        default=None,
    )
    scan.add_argument("--min-amount-ma20", type=float, default=None)
    scan.add_argument("--min-volume-ratio", type=float, default=None)
    scan.add_argument("--max-volume-ratio", type=float, default=None)
    scan.add_argument("--max-close-vs-trend", type=float, default=None)
    scan.add_argument("--min-close-vs-trend", type=float, default=None)
    scan.add_argument("--max-close-vs-cost", type=float, default=0.18)
    scan.add_argument("--min-price-position", type=float, default=0.30)
    scan.add_argument("--max-price-position", type=float, default=0.82)
    scan.add_argument("--min-distance-to-high", type=float, default=-0.35)
    scan.add_argument("--max-distance-to-high", type=float, default=-0.04)
    scan.add_argument("--filter-max-ret-20", type=float, default=None)
    scan.add_argument("--min-ret-60", type=float, default=0.18)
    scan.add_argument("--max-ret-60", type=float, default=0.30)
    scan.add_argument("--fast-trend-window", type=int, default=60)
    scan.add_argument("--pullback-window", type=int, default=20)
    scan.add_argument("--max-drawdown-from-high", type=float, default=0.32)
    scan.add_argument("--min-trend-slope-20", type=float, default=0.03)
    scan.add_argument("--require-positive-trend-slope", action="store_true")
    _add_strategy_arguments(scan)
    scan.set_defaults(func=scan_pattern)

    sentiment = subparsers.add_parser("sentiment-score", help="给候选股生成情绪面评分报告")
    sentiment.add_argument("--symbols", nargs="+", default=None)
    sentiment.add_argument("--watchlist", default=None)
    sentiment.add_argument("--latest-scan", action="store_true")
    sentiment.add_argument("--target-date", default=None)
    sentiment.add_argument("--news-days", type=int, default=7)
    sentiment.add_argument("--research-days", type=int, default=90)
    sentiment.add_argument("--hot-rank-top", type=int, default=500)
    sentiment.add_argument("--top", type=int, default=None)
    sentiment.add_argument("--display-top", type=int, default=30)
    sentiment.set_defaults(func=sentiment_score)

    theme = subparsers.add_parser("market-theme", help="生成市场主线观察报告")
    theme.add_argument("--target-date", default=None)
    theme.add_argument("--top", type=int, default=20)
    theme.set_defaults(func=market_theme)

    research = subparsers.add_parser("research-candidates", help="合成形态、情绪、主线和风险的候选池")
    research.add_argument("--scan-report", default=None)
    research.add_argument("--sentiment-report", default=None)
    research.add_argument("--target-date", default=None)
    research.add_argument("--top", type=int, default=30)
    research.add_argument("--risk-days", type=int, default=180)
    research.add_argument("--refresh-theme", action="store_true")
    research.add_argument(
        "--fetch-profiles",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    research.add_argument(
        "--fetch-notices",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    research.set_defaults(func=research_candidates)

    research_bt = subparsers.add_parser("research-backtest", help="回测研究候选池的技术代理组合")
    research_bt.add_argument("--symbols", nargs="+", default=None)
    research_bt.add_argument("--universe-file", default=None)
    research_bt.add_argument("--markets", nargs="+", default=["sh", "sz"])
    research_bt.add_argument("--include-st", action="store_true")
    research_bt.add_argument("--since", default=None)
    research_bt.add_argument("--until", default=None)
    research_bt.add_argument("--years", type=int, default=2)
    research_bt.add_argument("--top-n", type=int, default=10)
    research_bt.add_argument("--min-score", type=float, default=50.0)
    research_bt.add_argument("--stages", nargs="+", default=["watch", "near_breakout"])
    research_bt.add_argument("--min-amount-ma20", type=float, default=100_000_000.0)
    research_bt.add_argument("--min-volume-ratio", type=float, default=None)
    research_bt.add_argument("--max-close-vs-trend", type=float, default=0.25)
    research_bt.add_argument("--filter-max-ret-20", type=float, default=0.25)
    research_bt.add_argument("--require-positive-trend-slope", action=argparse.BooleanOptionalAction, default=True)
    research_bt.add_argument("--rebalance-frequency", choices=["D", "W", "M"], default="W")
    research_bt.add_argument("--limit", type=int, default=None)
    research_bt.set_defaults(func=research_backtest)

    research_opt = subparsers.add_parser("research-optimize", help="扫描研究候选池技术代理参数")
    research_opt.add_argument("--symbols", nargs="+", default=None)
    research_opt.add_argument("--universe-file", default=None)
    research_opt.add_argument("--markets", nargs="+", default=["sh", "sz"])
    research_opt.add_argument("--include-st", action="store_true")
    research_opt.add_argument("--since", default=None)
    research_opt.add_argument("--until", default=None)
    research_opt.add_argument("--years", type=int, default=2)
    research_opt.add_argument("--top-ns", default="5,10,20")
    research_opt.add_argument("--min-scores", default="45,50,55")
    research_opt.add_argument("--max-ret-20s", default="0.15,0.20,0.25")
    research_opt.add_argument("--rebalance-frequencies", nargs="+", default=["W", "M"])
    research_opt.add_argument("--stages", nargs="+", default=["watch", "near_breakout"])
    research_opt.add_argument("--min-amount-ma20", type=float, default=100_000_000.0)
    research_opt.add_argument("--min-volume-ratio", type=float, default=None)
    research_opt.add_argument("--max-close-vs-trend", type=float, default=0.25)
    research_opt.add_argument("--require-positive-trend-slope", action=argparse.BooleanOptionalAction, default=True)
    research_opt.add_argument("--limit", type=int, default=None)
    research_opt.add_argument("--display-top", type=int, default=20)
    research_opt.set_defaults(func=research_optimize)

    snapshot = subparsers.add_parser("snapshot-research", help="归档每日研究报告快照")
    snapshot.add_argument("--target-date", default=None)
    snapshot.add_argument("--scan-report", default=None)
    snapshot.add_argument("--sentiment-report", default=None)
    snapshot.add_argument("--theme-report", default=None)
    snapshot.add_argument("--research-report", default=None)
    snapshot.set_defaults(func=snapshot_research)

    daily_summary = subparsers.add_parser("daily-research-summary", help="生成每日市场选股复盘报告")
    daily_summary.add_argument("--target-date", default=None)
    daily_summary.add_argument("--snapshot-dir", default=None)
    daily_summary.add_argument("--top", type=int, default=30)
    daily_summary.set_defaults(func=daily_research_summary)

    review = subparsers.add_parser("research-review", help="复盘研究候选池的次日表现和错过样本")
    review.add_argument("--since", default=None)
    review.add_argument("--until", default=None)
    review.add_argument("--top-movers", type=int, default=20)
    review.add_argument("--universe-file", default=None)
    review.set_defaults(func=research_review)

    tracking = subparsers.add_parser("track-candidates", help="生成 A2/A3/B2 候选生命周期跟踪报告并写入仓库")
    tracking.add_argument("--since", default=None)
    tracking.add_argument("--until", default=None)
    tracking.add_argument("--snapshot-root", default=None)
    tracking.add_argument("--cache-dir", default=None)
    tracking.add_argument("--universe-file", default="data/universe/a_stock.csv")
    tracking.add_argument("--warehouse-dir", default=None)
    tracking.add_argument("--run-id", default=None)
    tracking.add_argument("--strategy-version", default="research_candidates_v1")
    tracking.add_argument("--gap-trade-days", type=int, default=3)
    tracking.add_argument("--top", type=int, default=50)
    tracking.add_argument("--write-warehouse", action=argparse.BooleanOptionalAction, default=True)
    tracking.set_defaults(func=track_candidates)

    warehouse_ingest_parser = subparsers.add_parser("warehouse-ingest", help="把最新研究报告写入 DuckDB + Parquet 仓库")
    warehouse_ingest_parser.add_argument("--target-date", default=None)
    warehouse_ingest_parser.add_argument("--reports-dir", default=None)
    warehouse_ingest_parser.add_argument("--warehouse-dir", default=None)
    warehouse_ingest_parser.add_argument("--run-id", default=None)
    warehouse_ingest_parser.set_defaults(func=warehouse_ingest)

    warehouse_status_parser = subparsers.add_parser("warehouse-status", help="查看研究仓库表和日期覆盖情况")
    warehouse_status_parser.add_argument("--warehouse-dir", default=None)
    warehouse_status_parser.set_defaults(func=warehouse_status)

    data_loop_parser = subparsers.add_parser("data-loop-status", help="查看数据闭环分层、仓库覆盖和 Obsidian 同步状态")
    data_loop_parser.add_argument("--target-date", default=None)
    data_loop_parser.add_argument("--plan-date", default=None)
    data_loop_parser.add_argument("--warehouse-dir", default=None)
    data_loop_parser.add_argument("--obsidian-root", default=None)
    data_loop_parser.set_defaults(func=data_loop_status)

    retention_parser = subparsers.add_parser("data-retention-plan", help="生成数据保留/清理 dry-run 预案")
    retention_parser.add_argument("--reports-days", type=int, default=14)
    retention_parser.add_argument("--ops-reports-days", type=int, default=60)
    retention_parser.add_argument("--logs-days", type=int, default=30)
    retention_parser.add_argument("--snapshots-days", type=int, default=30)
    retention_parser.add_argument("--top", type=int, default=50)
    retention_parser.set_defaults(func=data_retention_plan)

    warehouse_backfill_parser = subparsers.add_parser("warehouse-backfill-snapshots", help="把历史研究快照回填到仓库")
    warehouse_backfill_parser.add_argument("--since", default=None)
    warehouse_backfill_parser.add_argument("--until", default=None)
    warehouse_backfill_parser.add_argument("--snapshot-root", default=None)
    warehouse_backfill_parser.add_argument("--warehouse-dir", default=None)
    warehouse_backfill_parser.add_argument("--run-id", default=None)
    warehouse_backfill_parser.add_argument("--display-top", type=int, default=30)
    warehouse_backfill_parser.set_defaults(func=warehouse_backfill_snapshots)

    warehouse_universe_parser = subparsers.add_parser("warehouse-sync-universe", help="把股票池文件写入仓库维表")
    warehouse_universe_parser.add_argument("--universe-file", default="data/universe/a_stock.csv")
    warehouse_universe_parser.add_argument("--target-date", default=None)
    warehouse_universe_parser.add_argument("--warehouse-dir", default=None)
    warehouse_universe_parser.add_argument("--run-id", default=None)
    warehouse_universe_parser.set_defaults(func=warehouse_sync_universe)

    warehouse_candles_parser = subparsers.add_parser("warehouse-sync-candles", help="把本地日线 CSV 缓存同步成 Parquet")
    warehouse_candles_parser.add_argument("--symbols", nargs="+", default=None)
    warehouse_candles_parser.add_argument("--universe-file", default=None)
    warehouse_candles_parser.add_argument("--cache-dir", default=None)
    warehouse_candles_parser.add_argument("--source", default="akshare")
    warehouse_candles_parser.add_argument("--since", default=None)
    warehouse_candles_parser.add_argument("--until", default=None)
    warehouse_candles_parser.add_argument("--target-date", default=None)
    warehouse_candles_parser.add_argument("--warehouse-dir", default=None)
    warehouse_candles_parser.add_argument("--run-id", default=None)
    warehouse_candles_parser.add_argument("--limit", type=int, default=None)
    warehouse_candles_parser.add_argument("--force", action="store_true")
    warehouse_candles_parser.add_argument("--display-top", type=int, default=30)
    warehouse_candles_parser.set_defaults(func=warehouse_sync_candles)

    warehouse_review_parser = subparsers.add_parser("warehouse-review", help="从研究仓库汇总候选池复盘和错过样本")
    warehouse_review_parser.add_argument("--since", default=None)
    warehouse_review_parser.add_argument("--until", default=None)
    warehouse_review_parser.add_argument("--warehouse-dir", default=None)
    warehouse_review_parser.set_defaults(func=warehouse_review)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
