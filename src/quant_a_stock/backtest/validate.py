from __future__ import annotations

import pandas as pd

from quant_a_stock.backtest.engine import run_backtest, summarize_equity_curve
from quant_a_stock.config import BacktestConfig, DEFAULT_BACKTEST_CONFIG
from quant_a_stock.strategy.registry import generate_strategy_signals
from quant_a_stock.strategy.sma_trend_filter import generate_signals


def _yearly_rows_for_symbol(
    symbol: str,
    curve: pd.DataFrame,
) -> list[dict]:
    rows: list[dict] = []
    by_year = curve.groupby(curve["timestamp"].dt.year)
    for year, yearly_curve in by_year:
        if yearly_curve.empty:
            continue
        normalized = yearly_curve.copy()
        normalized["equity"] = (1 + normalized["strategy_return"]).cumprod()
        row = summarize_equity_curve(normalized, symbol=symbol)
        row["year"] = int(year)
        rows.append(row)
    return rows


def _portfolio_yearly_rows(curves: list[pd.DataFrame]) -> list[dict]:
    if not curves:
        return []

    return_frames = []
    exposure_frames = []
    entry_frames = []
    for idx, curve in enumerate(curves):
        keyed = curve.set_index("timestamp")
        return_frames.append(keyed["strategy_return"].rename(f"ret_{idx}"))
        exposure_frames.append((keyed["position"] > 0).astype(float).rename(f"exp_{idx}"))
        if "entry_trade" in keyed.columns:
            entry_frames.append(keyed["entry_trade"].rename(f"trade_{idx}"))

    returns = pd.concat(return_frames, axis=1).sort_index().fillna(0.0)
    exposures = pd.concat(exposure_frames, axis=1).sort_index().fillna(0.0)
    entries = (
        pd.concat(entry_frames, axis=1).sort_index().fillna(0.0)
        if entry_frames
        else pd.DataFrame(index=returns.index)
    )
    portfolio_return = returns.mean(axis=1)
    portfolio_exposure = exposures.mean(axis=1)

    portfolio = pd.DataFrame(
        {
            "timestamp": portfolio_return.index,
            "strategy_return": portfolio_return.values,
            "position": portfolio_exposure.values,
        }
    )
    portfolio["equity"] = (1 + portfolio["strategy_return"]).cumprod()

    rows: list[dict] = []
    for year, yearly_curve in portfolio.groupby(portfolio["timestamp"].dt.year):
        normalized = yearly_curve.copy()
        normalized["equity"] = (1 + normalized["strategy_return"]).cumprod()
        if entries.empty:
            trades = 0
        else:
            trades = int(entries.loc[entries.index.year == year].sum().sum())
        row = summarize_equity_curve(normalized, symbol="PORTFOLIO", trades=trades)
        row["year"] = int(year)
        rows.append(row)
    return rows


def validate_sma_trend_filter(
    candles_by_symbol: dict[str, pd.DataFrame],
    *,
    fast_window: int = 20,
    slow_window: int = 60,
    trend_window: int = 120,
    since: str | None = None,
    config: BacktestConfig = DEFAULT_BACKTEST_CONFIG,
) -> pd.DataFrame:
    rows: list[dict] = []
    curves: list[pd.DataFrame] = []

    for symbol, candles in candles_by_symbol.items():
        frame = candles.copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"])
        frame = frame.reset_index(drop=True)
        signal = generate_signals(
            frame,
            fast_window=fast_window,
            slow_window=slow_window,
            trend_window=trend_window,
        )
        result = run_backtest(frame, signal, symbol=symbol, config=config)
        curve = result.equity_curve
        if since:
            curve = curve[curve["timestamp"] >= pd.Timestamp(since)].reset_index(drop=True)
        curves.append(curve)
        rows.extend(_yearly_rows_for_symbol(symbol, curve))

    rows.extend(_portfolio_yearly_rows(curves))
    if not rows:
        return pd.DataFrame()
    ordered = pd.DataFrame(rows)
    return ordered.sort_values(["year", "symbol"]).reset_index(drop=True)


def validate_strategy(
    candles_by_symbol: dict[str, pd.DataFrame],
    *,
    strategy_name: str,
    strategy_params: dict[str, int | float] | None = None,
    since: str | None = None,
    config: BacktestConfig = DEFAULT_BACKTEST_CONFIG,
) -> pd.DataFrame:
    rows: list[dict] = []
    curves: list[pd.DataFrame] = []
    params = strategy_params or {}

    for symbol, candles in candles_by_symbol.items():
        frame = candles.copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"])
        frame = frame.reset_index(drop=True)
        signal = generate_strategy_signals(strategy_name, frame, **params)
        result = run_backtest(frame, signal, symbol=symbol, config=config)
        curve = result.equity_curve
        if since:
            curve = curve[curve["timestamp"] >= pd.Timestamp(since)].reset_index(drop=True)
        curves.append(curve)
        symbol_rows = _yearly_rows_for_symbol(symbol, curve)
        for row in symbol_rows:
            row["strategy"] = strategy_name
        rows.extend(symbol_rows)

    portfolio_rows = _portfolio_yearly_rows(curves)
    for row in portfolio_rows:
        row["strategy"] = strategy_name
    rows.extend(portfolio_rows)

    if not rows:
        return pd.DataFrame()
    ordered = pd.DataFrame(rows)
    columns = ["strategy"] + [column for column in ordered.columns if column != "strategy"]
    return ordered.loc[:, columns].sort_values(["year", "symbol"]).reset_index(drop=True)
