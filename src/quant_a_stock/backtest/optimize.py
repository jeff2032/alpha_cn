from __future__ import annotations

from itertools import product
from typing import Iterable

import pandas as pd

from quant_a_stock.backtest.engine import run_backtest
from quant_a_stock.config import BacktestConfig, DEFAULT_BACKTEST_CONFIG
from quant_a_stock.strategy.sma_trend_filter import generate_signals


def parameter_grid(
    fast_windows: Iterable[int],
    slow_windows: Iterable[int],
    trend_windows: Iterable[int],
) -> list[dict[str, int]]:
    rows: list[dict[str, int]] = []
    for fast, slow, trend in product(fast_windows, slow_windows, trend_windows):
        if fast >= slow:
            continue
        rows.append(
            {
                "fast_window": int(fast),
                "slow_window": int(slow),
                "trend_window": int(trend),
            }
        )
    return rows


def optimize_sma_trend_filter(
    candles_by_symbol: dict[str, pd.DataFrame],
    *,
    fast_windows: Iterable[int],
    slow_windows: Iterable[int],
    trend_windows: Iterable[int],
    config: BacktestConfig = DEFAULT_BACKTEST_CONFIG,
) -> pd.DataFrame:
    results: list[dict] = []
    for params in parameter_grid(fast_windows, slow_windows, trend_windows):
        symbol_metrics = []
        for symbol, candles in candles_by_symbol.items():
            signal = generate_signals(candles, **params)
            result = run_backtest(candles, signal, symbol=symbol, config=config)
            symbol_metrics.append(result.metrics)

        metrics = pd.DataFrame(symbol_metrics)
        row = {
            **params,
            "symbols": ",".join(candles_by_symbol.keys()),
            "avg_return_pct": float(metrics["return_pct"].mean()),
            "avg_max_drawdown": float(metrics["max_drawdown"].mean()),
            "avg_sharpe": float(metrics["sharpe"].mean()),
            "total_trades": int(metrics["trades"].sum()),
            "avg_exposure_pct": float(metrics["exposure_pct"].mean()),
        }
        results.append(row)

    output = pd.DataFrame(results)
    if output.empty:
        return output
    output = output.sort_values(
        ["avg_return_pct", "avg_sharpe", "avg_max_drawdown"],
        ascending=[False, False, False],
    )
    output.insert(0, "rank", range(1, len(output) + 1))
    return output.reset_index(drop=True)

