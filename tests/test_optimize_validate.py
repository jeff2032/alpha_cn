from __future__ import annotations

import numpy as np
import pandas as pd

from quant_a_stock.backtest.optimize import optimize_sma_trend_filter
from quant_a_stock.backtest.validate import validate_sma_trend_filter


def _multi_year_candles(symbol: str) -> pd.DataFrame:
    days = 520
    close = pd.Series(np.linspace(10, 18, days))
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2022-01-03", periods=days, freq="B"),
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000_000,
            "amount": close * 1_000_000,
            "symbol": symbol,
        }
    )


def test_optimize_returns_ranked_rows() -> None:
    candles_by_symbol = {"510300": _multi_year_candles("510300")}

    result = optimize_sma_trend_filter(
        candles_by_symbol,
        fast_windows=[5, 10],
        slow_windows=[20],
        trend_windows=[40],
    )

    assert result["rank"].tolist() == [1, 2]
    assert {"avg_return_pct", "avg_sharpe", "total_trades"}.issubset(result.columns)


def test_validate_includes_portfolio_row() -> None:
    candles_by_symbol = {
        "510300": _multi_year_candles("510300"),
        "159915": _multi_year_candles("159915"),
    }

    result = validate_sma_trend_filter(
        candles_by_symbol,
        fast_window=5,
        slow_window=20,
        trend_window=40,
        since="2022-01-01",
    )

    assert "PORTFOLIO" in set(result["symbol"])
    assert {"return_pct", "max_drawdown", "sharpe", "trades", "exposure_pct"}.issubset(
        result.columns
    )

