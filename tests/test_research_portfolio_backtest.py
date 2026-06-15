from __future__ import annotations

import pandas as pd

from quant_a_stock.backtest.research_portfolio import ResearchPortfolioConfig
from quant_a_stock.backtest.research_portfolio import optimize_research_portfolio
from quant_a_stock.backtest.research_portfolio import run_research_portfolio_backtest
from quant_a_stock.screening.patterns import BaseBreakoutSetupConfig


def _candles(symbol: str, drift: float) -> pd.DataFrame:
    dates = pd.bdate_range("2023-01-02", periods=360)
    close = pd.Series(range(len(dates)), dtype=float).map(lambda index: 10 + index * drift)
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 10_000_000,
            "amount": close * 10_000_000,
            "symbol": symbol,
        }
    )


def test_research_portfolio_backtest_runs_on_synthetic_data() -> None:
    result = run_research_portfolio_backtest(
        {
            "000001": _candles("000001", 0.01),
            "000002": _candles("000002", 0.02),
        },
        since="2024-01-01",
        until="2024-05-01",
        setup_config=BaseBreakoutSetupConfig(
            base_window=60,
            trend_window=60,
            volume_window=20,
            max_base_range=1.0,
            proximity_pct=0.10,
            max_ret_20=1.0,
        ),
        portfolio_config=ResearchPortfolioConfig(
            top_n=1,
            min_score=0,
            min_amount_ma20=1,
            max_close_vs_trend=1.0,
            max_ret_20=1.0,
            rebalance_frequency="W",
            allow_stages=("watch", "near_breakout", "breakout"),
        ),
    )

    assert not result.equity_curve.empty
    assert result.metrics["holding_rows"] > 0
    assert result.metrics["exposure_pct"] > 0
    assert result.equity_curve["holding_count"].max() <= 1
    assert not result.yearly.empty


def test_optimize_research_portfolio_scans_parameter_grid() -> None:
    result = optimize_research_portfolio(
        {
            "000001": _candles("000001", 0.01),
            "000002": _candles("000002", 0.02),
        },
        since="2024-01-01",
        until="2024-05-01",
        top_ns=[1, 2],
        min_scores=[0],
        max_ret_20s=[1.0],
        rebalance_frequencies=["W"],
        min_amount_ma20=1,
        max_close_vs_trend=1.0,
        allow_stages=("watch", "near_breakout", "breakout"),
        setup_config=BaseBreakoutSetupConfig(
            base_window=60,
            trend_window=60,
            volume_window=20,
            max_base_range=1.0,
            proximity_pct=0.10,
            max_ret_20=1.0,
        ),
    )

    assert len(result) == 2
    assert result["rank"].tolist() == [1, 2]
    assert set(result["top_n"]) == {1, 2}
