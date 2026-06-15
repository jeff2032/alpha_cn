from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from quant_a_stock.config import BacktestConfig, DEFAULT_BACKTEST_CONFIG
from quant_a_stock.risk.rules import RiskConfig, apply_basic_risk_rules
from quant_a_stock.strategy.base import assert_long_only_signal


TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class BacktestResult:
    symbol: str
    equity_curve: pd.DataFrame
    metrics: dict[str, float | int | str]


def _max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    running_max = equity.cummax()
    drawdown = equity / running_max - 1
    return float(drawdown.min())


def _sharpe(daily_returns: pd.Series) -> float:
    std = daily_returns.std(ddof=0)
    if std == 0 or np.isnan(std):
        return 0.0
    return float(daily_returns.mean() / std * np.sqrt(TRADING_DAYS_PER_YEAR))


def summarize_equity_curve(
    curve: pd.DataFrame,
    *,
    symbol: str,
    trades: int | None = None,
) -> dict[str, float | int | str]:
    if curve.empty:
        return {
            "symbol": symbol,
            "return_pct": 0.0,
            "max_drawdown": 0.0,
            "sharpe": 0.0,
            "trades": 0,
            "exposure_pct": 0.0,
        }

    total_return = curve["equity"].iloc[-1] / curve["equity"].iloc[0] - 1
    if "entry_trade" in curve.columns:
        inferred_trades = int(curve["entry_trade"].sum())
    else:
        inferred_trades = int((curve["position"].diff().fillna(curve["position"]) > 0).sum())
    return {
        "symbol": symbol,
        "return_pct": float(total_return),
        "max_drawdown": _max_drawdown(curve["equity"]),
        "sharpe": _sharpe(curve["strategy_return"]),
        "trades": inferred_trades if trades is None else int(trades),
        "exposure_pct": float(curve["position"].clip(lower=0, upper=1).mean()),
    }


def _build_position(
    signal: pd.Series,
    *,
    config: BacktestConfig,
) -> pd.Series:
    position = signal.shift(1).fillna(0.0) if config.trade_on_next_bar else signal.fillna(0.0)
    return position.astype(float)


def run_backtest(
    candles: pd.DataFrame,
    signal: pd.Series,
    *,
    symbol: str,
    config: BacktestConfig = DEFAULT_BACKTEST_CONFIG,
    risk_config: RiskConfig = RiskConfig(),
) -> BacktestResult:
    if candles.empty:
        raise ValueError("Cannot backtest empty candles")

    frame = candles.copy().reset_index(drop=True)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    frame = frame.sort_values("timestamp").reset_index(drop=True)

    aligned_signal = signal.reset_index(drop=True).reindex(frame.index).fillna(0)
    assert_long_only_signal(aligned_signal.astype(int))

    filtered_signal = apply_basic_risk_rules(frame, aligned_signal, config=risk_config)
    position = _build_position(filtered_signal, config=config)

    close_return = frame["close"].pct_change().fillna(0.0)
    delta = position.diff().fillna(position)
    buy_turnover = delta.clip(lower=0)
    sell_turnover = (-delta).clip(lower=0)

    buy_cost = buy_turnover * (config.buy_commission_rate + config.transfer_fee_rate)
    sell_cost = sell_turnover * (
        config.sell_commission_rate + config.stamp_tax_rate + config.transfer_fee_rate
    )
    cost = buy_cost + sell_cost

    gross_return = position * close_return
    strategy_return = gross_return - cost
    equity = config.initial_cash * (1 + strategy_return).cumprod()

    curve = pd.DataFrame(
        {
            "timestamp": frame["timestamp"],
            "close": frame["close"],
            "signal": aligned_signal.astype(float),
            "position": position,
            "buy_turnover": buy_turnover,
            "sell_turnover": sell_turnover,
            "entry_trade": (delta > 0).astype(int),
            "exit_trade": (delta < 0).astype(int),
            "close_return": close_return,
            "gross_return": gross_return,
            "cost": cost,
            "strategy_return": strategy_return,
            "equity": equity,
        }
    )
    metrics = summarize_equity_curve(curve, symbol=symbol)
    return BacktestResult(symbol=symbol, equity_curve=curve, metrics=metrics)
