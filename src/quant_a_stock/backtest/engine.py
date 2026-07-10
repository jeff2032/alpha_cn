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
    if config.execution_model == "realistic":
        return _run_realistic_backtest(
            frame,
            aligned_signal=aligned_signal,
            filtered_signal=filtered_signal,
            symbol=symbol,
            config=config,
        )
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


def _run_realistic_backtest(
    frame: pd.DataFrame,
    *,
    aligned_signal: pd.Series,
    filtered_signal: pd.Series,
    symbol: str,
    config: BacktestConfig,
) -> BacktestResult:
    targets = _build_position(filtered_signal, config=config).clip(0.0, 1.0)
    cash = float(config.initial_cash)
    shares = 0
    previous_equity = float(config.initial_cash)
    rows: list[dict] = []
    trade_count = 0

    for index, candle in frame.iterrows():
        open_price = float(candle["open"])
        close_price = float(candle["close"])
        target_weight = float(targets.iloc[index])
        equity_at_open = cash + shares * open_price
        desired_shares = _round_lot(
            equity_at_open * target_weight / open_price if open_price > 0 else 0,
            config.lot_size,
        )
        delta = desired_shares - shares
        buy_qty = 0
        sell_qty = 0
        commission = 0.0
        tax = 0.0
        transfer_fee = 0.0
        slippage_cost = 0.0
        blocked_reason = ""

        if delta < 0:
            blocked_reason = trade_block_reason(frame, index, side="sell")
            if not blocked_reason:
                sell_qty = min(shares, -delta)
                fill_price = open_price * (1 - config.slippage_bps / 10_000)
                value = sell_qty * fill_price
                commission = max(config.min_commission, value * config.sell_commission_rate)
                tax = value * config.stamp_tax_rate
                transfer_fee = value * config.transfer_fee_rate
                slippage_cost = sell_qty * max(0.0, open_price - fill_price)
                cash += value - commission - tax - transfer_fee
                shares -= sell_qty
                trade_count += 1
        elif delta > 0:
            blocked_reason = trade_block_reason(frame, index, side="buy")
            if not blocked_reason:
                fill_price = open_price * (1 + config.slippage_bps / 10_000)
                buy_qty = _affordable_lot_quantity(
                    desired=delta,
                    cash=cash,
                    fill_price=fill_price,
                    commission_rate=config.buy_commission_rate,
                    min_commission=config.min_commission,
                    transfer_fee_rate=config.transfer_fee_rate,
                    lot_size=config.lot_size,
                )
                if buy_qty > 0:
                    value = buy_qty * fill_price
                    commission = max(config.min_commission, value * config.buy_commission_rate)
                    transfer_fee = value * config.transfer_fee_rate
                    slippage_cost = buy_qty * max(0.0, fill_price - open_price)
                    cash -= value + commission + transfer_fee
                    shares += buy_qty
                    trade_count += 1

        equity = cash + shares * close_price
        strategy_return = equity / previous_equity - 1 if previous_equity > 0 else 0.0
        position = shares * close_price / equity if equity > 0 else 0.0
        rows.append(
            {
                "timestamp": candle["timestamp"],
                "close": close_price,
                "signal": float(aligned_signal.iloc[index]),
                "target_position": target_weight,
                "position": position,
                "shares": shares,
                "cash": cash,
                "buy_quantity": buy_qty,
                "sell_quantity": sell_qty,
                "entry_trade": int(buy_qty > 0),
                "exit_trade": int(sell_qty > 0),
                "commission": commission,
                "stamp_tax": tax,
                "transfer_fee": transfer_fee,
                "slippage_cost": slippage_cost,
                "cost": commission + tax + transfer_fee + slippage_cost,
                "blocked_reason": blocked_reason,
                "strategy_return": strategy_return,
                "equity": equity,
            }
        )
        previous_equity = equity

    curve = pd.DataFrame(rows)
    metrics = summarize_equity_curve(curve, symbol=symbol, trades=trade_count)
    metrics["blocked_trades"] = int((curve["blocked_reason"] != "").sum())
    metrics["execution_model"] = "realistic_open"
    return BacktestResult(symbol=symbol, equity_curve=curve, metrics=metrics)


def trade_block_reason(frame: pd.DataFrame, index: int, *, side: str) -> str:
    row = frame.iloc[index]
    if bool(row.get("is_suspended", False)) or float(row.get("volume", 0) or 0) <= 0:
        return "停牌不可成交"
    if side == "buy" and bool(row.get("is_limit_up", False)):
        return "涨停不可买入"
    if side == "sell" and bool(row.get("is_limit_down", False)):
        return "跌停不可卖出"
    if index <= 0:
        return ""
    previous_close = float(frame.iloc[index - 1].get("close", 0) or 0)
    open_price = float(row.get("open", 0) or 0)
    if previous_close <= 0 or open_price <= 0:
        return "价格无效"
    limit_pct = float(row.get("price_limit_pct", 0.10) or 0.10)
    tolerance = 0.0005
    if side == "buy" and open_price >= previous_close * (1 + limit_pct) * (1 - tolerance):
        return "涨停不可买入"
    if side == "sell" and open_price <= previous_close * (1 - limit_pct) * (1 + tolerance):
        return "跌停不可卖出"
    return ""


def _round_lot(quantity: float, lot_size: int) -> int:
    lot = max(1, int(lot_size))
    return max(0, int(quantity // lot) * lot)


def _affordable_lot_quantity(
    *,
    desired: int,
    cash: float,
    fill_price: float,
    commission_rate: float,
    min_commission: float,
    transfer_fee_rate: float,
    lot_size: int,
) -> int:
    quantity = _round_lot(desired, lot_size)
    while quantity > 0:
        value = quantity * fill_price
        fees = max(min_commission, value * commission_rate) + value * transfer_fee_rate
        if value + fees <= cash + 1e-9:
            return quantity
        quantity -= max(1, lot_size)
    return 0
