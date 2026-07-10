from __future__ import annotations

import numpy as np
import pandas as pd

from quant_a_stock.backtest.engine import BacktestConfig, run_backtest
from quant_a_stock.strategy.registry import available_strategy_names
from quant_a_stock.strategy.registry import generate_strategy_signals
from quant_a_stock.strategy.sma_trend_filter import generate_signals


def _sample_candles(days: int = 180) -> pd.DataFrame:
    close = pd.Series(np.linspace(10, 20, days))
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2023-01-01", periods=days, freq="B"),
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000_000,
            "amount": close * 1_000_000,
            "symbol": "510300",
        }
    )


def test_sma_trend_filter_generates_long_only_signal() -> None:
    candles = _sample_candles()

    signal = generate_signals(candles, fast_window=5, slow_window=10, trend_window=20)

    assert set(signal.unique()).issubset({0, 1})
    assert signal.iloc[:19].sum() == 0
    assert signal.iloc[-1] == 1


def test_registered_research_strategies_generate_long_only_signals() -> None:
    candles = _sample_candles(220)

    for strategy_name in available_strategy_names():
        signal = generate_strategy_signals(
            strategy_name,
            candles,
            fast_window=5,
            slow_window=10,
            trend_window=20,
            breakout_window=20,
            exit_window=10,
            ema_fast_window=5,
            ema_slow_window=10,
            rsi_window=14,
            rsi_entry=45,
            rsi_exit=60,
        )
        assert len(signal) == len(candles)
        assert set(signal.unique()).issubset({0, 1})


def test_backtest_uses_shifted_signal_and_costs() -> None:
    candles = _sample_candles(40)
    signal = pd.Series([0, 1] + [1] * 38)
    config = BacktestConfig(
        initial_cash=100_000,
        buy_commission_rate=0.001,
        sell_commission_rate=0.001,
        stamp_tax_rate=0.001,
        transfer_fee_rate=0,
        trade_on_next_bar=True,
    )

    result = run_backtest(candles, signal, symbol="510300", config=config)

    assert result.equity_curve.loc[1, "position"] == 0
    assert 0.95 < result.equity_curve.loc[2, "position"] < 1
    assert result.equity_curve.loc[2, "shares"] % 100 == 0
    assert result.equity_curve.loc[2, "commission"] >= 5
    assert result.equity_curve["cost"].sum() > 0
    assert result.metrics["trades"] == 1


def test_realistic_backtest_blocks_limit_up_buy() -> None:
    candles = _sample_candles(8)
    candles.loc[2, ["open", "high", "low", "close"]] = candles.loc[1, "close"] * 1.10
    signal = pd.Series([0, 1] + [1] * 6)

    result = run_backtest(candles, signal, symbol="000001")

    assert result.equity_curve.loc[2, "shares"] == 0
    assert result.equity_curve.loc[2, "blocked_reason"] == "涨停不可买入"
    assert result.metrics["blocked_trades"] >= 1
