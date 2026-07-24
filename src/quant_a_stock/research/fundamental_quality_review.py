from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from quant_a_stock.config import DEFAULT_PATHS
from quant_a_stock.data.universe import normalize_symbol


DEFAULT_HORIZONS = (3, 5, 10, 20)


def evaluate_fundamental_quality_history(
    history: pd.DataFrame,
    *,
    benchmark_symbol: str = "510300",
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    cache_root: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if history.empty:
        return pd.DataFrame(), pd.DataFrame()
    root = cache_root or DEFAULT_PATHS.root / "data" / "cache" / "akshare" / "daily"
    benchmark = _load_candles(root / f"{normalize_symbol(benchmark_symbol)}.csv")
    rows: list[dict] = []
    candle_cache: dict[str, pd.DataFrame] = {}

    for _, item in history.iterrows():
        symbol = normalize_symbol(item.get("symbol", ""))
        candles = candle_cache.setdefault(symbol, _load_candles(root / f"{symbol}.csv"))
        signal_date = pd.Timestamp(item["target_date"]).normalize()
        outcome = dict(item)
        outcome["entry_date"] = ""
        outcome["entry_open"] = np.nan
        for horizon in horizons:
            outcome[f"return_{horizon}d_pct"] = np.nan
            outcome[f"benchmark_{horizon}d_pct"] = np.nan
            outcome[f"excess_{horizon}d_pct"] = np.nan
        if candles.empty:
            outcome["outcome_error"] = "missing_candles"
            rows.append(outcome)
            continue

        future = candles[candles["timestamp"] > signal_date].reset_index(drop=True)
        if future.empty:
            outcome["outcome_error"] = "no_next_session"
            rows.append(outcome)
            continue
        entry = future.iloc[0]
        entry_open = float(entry["open"])
        outcome["entry_date"] = entry["timestamp"].date().isoformat()
        outcome["entry_open"] = entry_open
        benchmark_future = benchmark[benchmark["timestamp"] > signal_date].reset_index(drop=True)
        benchmark_entry = float(benchmark_future.iloc[0]["open"]) if not benchmark_future.empty else np.nan

        for horizon in horizons:
            exit_index = horizon - 1
            if exit_index >= len(future) or entry_open <= 0:
                continue
            stock_return = float(future.iloc[exit_index]["close"]) / entry_open - 1.0
            benchmark_return = np.nan
            if exit_index < len(benchmark_future) and benchmark_entry > 0:
                benchmark_return = float(benchmark_future.iloc[exit_index]["close"]) / benchmark_entry - 1.0
            outcome[f"return_{horizon}d_pct"] = round(stock_return * 100, 4)
            outcome[f"benchmark_{horizon}d_pct"] = (
                round(benchmark_return * 100, 4) if np.isfinite(benchmark_return) else np.nan
            )
            outcome[f"excess_{horizon}d_pct"] = (
                round((stock_return - benchmark_return) * 100, 4) if np.isfinite(benchmark_return) else np.nan
            )
        outcome["outcome_error"] = ""
        rows.append(outcome)

    details = pd.DataFrame(rows)
    summary = summarize_fundamental_quality_outcomes(details, horizons=horizons)
    return details, summary


def summarize_fundamental_quality_outcomes(
    details: pd.DataFrame,
    *,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> pd.DataFrame:
    if details.empty:
        return pd.DataFrame()
    frame = details.copy()
    frame["quality_group"] = frame["quality_verdict"].map(
        {
            "pass": "通过",
            "watch": "观察",
            "reject": "否决",
            "specialized_review": "专用模型",
            "data_insufficient": "数据不足",
        }
    ).fillna("其他")
    rows: list[dict] = []
    for group_name, group in frame.groupby("quality_group", dropna=False):
        row: dict[str, object] = {
            "quality_group": group_name,
            "signals": int(len(group)),
            "symbols": int(group["symbol"].nunique()),
            "dates": int(group["target_date"].nunique()),
        }
        for horizon in horizons:
            returns = pd.to_numeric(group[f"return_{horizon}d_pct"], errors="coerce").dropna()
            excess = pd.to_numeric(group[f"excess_{horizon}d_pct"], errors="coerce").dropna()
            row[f"covered_{horizon}d"] = int(len(returns))
            row[f"avg_return_{horizon}d_pct"] = _mean(returns)
            row[f"median_return_{horizon}d_pct"] = _median(returns)
            row[f"win_rate_{horizon}d_pct"] = _rate(returns > 0)
            row[f"avg_excess_{horizon}d_pct"] = _mean(excess)
            row[f"loss_10pct_rate_{horizon}d_pct"] = _rate(returns <= -10)
        rows.append(row)
    return pd.DataFrame(rows).sort_values("quality_group").reset_index(drop=True)


def _load_candles(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        frame = pd.read_csv(path, usecols=["timestamp", "open", "close"])
    except (OSError, ValueError, pd.errors.ParserError, pd.errors.EmptyDataError):
        return pd.DataFrame()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce").dt.normalize()
    frame["open"] = pd.to_numeric(frame["open"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    return frame.dropna(subset=["timestamp", "open", "close"]).sort_values("timestamp").drop_duplicates("timestamp")


def _mean(values: pd.Series) -> float:
    return round(float(values.mean()), 4) if not values.empty else np.nan


def _median(values: pd.Series) -> float:
    return round(float(values.median()), 4) if not values.empty else np.nan


def _rate(mask: pd.Series) -> float:
    return round(float(mask.mean() * 100), 2) if not mask.empty else np.nan
