from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from quant_a_stock.backtest.engine import trade_block_reason
from quant_a_stock.config import BacktestConfig, DEFAULT_BACKTEST_CONFIG, DEFAULT_PATHS
from quant_a_stock.data.cache import load_daily_cache


SHADOW_PLAN_COLUMNS = [
    "plan_id",
    "target_date",
    "plan_date",
    "symbol",
    "name",
    "target_weight",
    "signal_type",
    "action_bucket",
    "expected_horizon",
    "max_hold_days",
    "industry",
    "research_score",
    "risk_level",
    "market_regime",
    "market_score",
    "market_total_cap",
    "observe_condition",
    "invalid_condition",
    "frozen_at",
    "status",
]


@dataclass(frozen=True)
class ShadowPortfolioResult:
    equity: pd.DataFrame
    trades: pd.DataFrame
    positions: pd.DataFrame


@dataclass(frozen=True)
class ShadowBackfillResult:
    plans: pd.DataFrame
    summary: pd.DataFrame
    plans_root: Path


def freeze_shadow_plan(
    signals: pd.DataFrame,
    *,
    target_date: str,
    plan_date: str,
    top: int = 10,
    max_single_weight: float = 0.15,
    max_total_weight: float = 0.80,
    max_industry_weight: float = 0.30,
    market_regime: str = "",
    market_score: float = 0.0,
) -> pd.DataFrame:
    if signals.empty:
        return pd.DataFrame(columns=SHADOW_PLAN_COLUMNS)
    frame = signals.copy()
    frame["symbol"] = frame["symbol"].astype(str).str.zfill(6)
    frame = frame[frame["risk_level"].isin(["低", "中", "未标注"])]
    priority = {"buy_watch": 1, "upgrade_watch": 2}
    frame["_priority"] = frame["signal_type"].map(priority).fillna(9)
    frame = frame[frame["_priority"] < 9].sort_values(["_priority", "research_score"], ascending=[True, False])

    market_cap = market_position_cap(market_regime) if market_regime else max_total_weight
    effective_total_weight = min(max_total_weight, market_cap)
    rows = []
    total_weight = 0.0
    industry_weights: dict[str, float] = {}
    base_weight = min(max_single_weight, effective_total_weight / max(1, top))
    for _, row in frame.iterrows():
        if len(rows) >= top or total_weight >= effective_total_weight - 1e-9:
            break
        industry = str(row.get("theme_cluster", "") or row.get("matched_theme", "") or "")
        weight = min(base_weight, effective_total_weight - total_weight)
        if industry:
            weight = min(weight, max_industry_weight - industry_weights.get(industry, 0.0))
        if weight <= 1e-9:
            continue
        rows.append(
            {
                "plan_id": f"{plan_date}_{str(row['symbol']).zfill(6)}",
                "target_date": target_date,
                "plan_date": plan_date,
                "symbol": str(row["symbol"]).zfill(6),
                "name": row.get("name", ""),
                "target_weight": round(weight, 6),
                "signal_type": row.get("signal_type", ""),
                "action_bucket": row.get("action_bucket", ""),
                "expected_horizon": row.get("expected_horizon", ""),
                "max_hold_days": _max_hold_days(row.get("expected_horizon", "")),
                "industry": industry,
                "research_score": row.get("research_score", 0),
                "risk_level": row.get("risk_level", ""),
                "market_regime": market_regime,
                "market_score": round(float(market_score), 2),
                "market_total_cap": round(effective_total_weight, 4),
                "observe_condition": row.get("observe_condition", ""),
                "invalid_condition": row.get("invalid_condition", ""),
                "frozen_at": datetime.now().isoformat(timespec="seconds"),
                "status": "frozen",
            }
        )
        total_weight += weight
        if industry:
            industry_weights[industry] = industry_weights.get(industry, 0.0) + weight
    return pd.DataFrame(rows, columns=SHADOW_PLAN_COLUMNS)


def market_position_cap(regime: str) -> float:
    return {
        "强势": 0.80,
        "震荡偏强": 0.60,
        "震荡": 0.40,
        "防守": 0.20,
        "未知": 0.20,
    }.get(str(regime or ""), 0.20)


def backfill_shadow_plans(
    *,
    since: str,
    until: str,
    snapshot_root: Path | None = None,
    plans_root: Path | None = None,
    cache_dir: Path | None = None,
    top: int = 10,
    signal_top: int = 80,
    max_single_weight: float = 0.15,
    max_total_weight: float = 0.80,
    max_industry_weight: float = 0.30,
    overwrite: bool = True,
) -> ShadowBackfillResult:
    from quant_a_stock.data.calendar import cached_trading_dates
    from quant_a_stock.research.decision_signal import build_decision_signals
    from quant_a_stock.research.summary import build_market_temperature

    snapshots = snapshot_root or DEFAULT_PATHS.root / "data" / "snapshots" / "research"
    output_root = plans_root or DEFAULT_PATHS.root / "data" / "shadow" / "backfill" / "plans"
    start = pd.Timestamp(since).normalize()
    end = pd.Timestamp(until).normalize()
    trading_dates = cached_trading_dates(cache_dir=cache_dir)
    next_session = {
        trading_dates[index]: trading_dates[index + 1]
        for index in range(len(trading_dates) - 1)
    }
    plans = []
    summary_rows = []
    for directory in sorted(snapshots.glob("????-??-??")):
        target = pd.Timestamp(directory.name).normalize()
        if target < start or target > end or target not in next_session:
            continue
        source = directory / "research_candidates.csv"
        if not source.exists():
            continue
        candidates = pd.read_csv(source, dtype={"symbol": str})
        plan_date = next_session[target].date().isoformat()
        signals = build_decision_signals(
            candidates,
            target_date=target.date().isoformat(),
            plan_date=plan_date,
            top=signal_top,
        )
        market, _ = build_market_temperature(target_date=target.date().isoformat())
        plan = freeze_shadow_plan(
            signals,
            target_date=target.date().isoformat(),
            plan_date=plan_date,
            top=max(5, min(10, int(top))),
            max_single_weight=max_single_weight,
            max_total_weight=max_total_weight,
            max_industry_weight=max_industry_weight,
            market_regime=str(market.get("regime", "未知")),
            market_score=float(market.get("score", 0.0)),
        )
        save_shadow_plan(plan, plan_date=plan_date, root=output_root, overwrite=overwrite)
        if not plan.empty:
            plans.append(plan)
        summary_rows.append(
            {
                "target_date": target.date().isoformat(),
                "plan_date": plan_date,
                "candidate_count": len(candidates),
                "signal_count": len(signals),
                "planned_count": len(plan),
                "planned_weight": pd.to_numeric(
                    plan.get("target_weight", pd.Series(dtype=float)), errors="coerce"
                ).sum(),
                "market_regime": market.get("regime", "未知"),
                "market_score": market.get("score", 0.0),
                "market_total_cap": market_position_cap(str(market.get("regime", "未知"))),
                "underfilled": len(plan) < 5,
            }
        )
    combined = pd.concat(plans, ignore_index=True) if plans else pd.DataFrame(columns=SHADOW_PLAN_COLUMNS)
    return ShadowBackfillResult(combined, pd.DataFrame(summary_rows), output_root)


def save_shadow_plan(plan: pd.DataFrame, *, plan_date: str, root: Path | None = None, overwrite: bool = False) -> Path:
    plan_root = root or DEFAULT_PATHS.root / "data" / "shadow" / "plans"
    output_dir = plan_root / f"plan_date={plan_date}"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "plan.csv"
    if path.exists() and not overwrite:
        raise FileExistsError(f"影子组合计划已经冻结，拒绝覆盖: {path}")
    plan.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def evaluate_shadow_portfolio(
    *,
    plans_root: Path | None = None,
    cache_dir: Path | None = None,
    until: str | None = None,
    since: str | None = None,
    config: BacktestConfig = DEFAULT_BACKTEST_CONFIG,
) -> ShadowPortfolioResult:
    root = plans_root or DEFAULT_PATHS.root / "data" / "shadow" / "plans"
    plans = _load_plans(root)
    if since and not plans.empty:
        plans = plans[plans["plan_date"] >= pd.Timestamp(since)].copy()
    if until and not plans.empty:
        plans = plans[plans["plan_date"] <= pd.Timestamp(until)].copy()
    if plans.empty:
        return ShadowPortfolioResult(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    symbols = sorted(plans["symbol"].astype(str).str.zfill(6).unique())
    candles = {symbol: _load_candles(symbol, cache_dir=cache_dir) for symbol in symbols}
    all_dates = sorted(
        {
            date
            for frame in candles.values()
            for date in frame.index
            if date >= pd.Timestamp(plans["plan_date"].min()) and (not until or date <= pd.Timestamp(until))
        }
    )
    plan_by_date = {pd.Timestamp(date): group.copy() for date, group in plans.groupby("plan_date")}
    cash = float(config.initial_cash)
    shares = {symbol: 0 for symbol in symbols}
    entry_index: dict[str, int] = {}
    max_hold = dict(zip(plans["symbol"], plans["max_hold_days"]))
    active_targets: dict[str, float] = {}
    equity_rows = []
    trade_rows = []
    position_rows = []
    previous_equity = cash

    for day_index, date in enumerate(all_dates):
        daily_plan = plan_by_date.get(date)
        rebalance = daily_plan is not None
        if rebalance:
            active_targets = dict(zip(daily_plan["symbol"], daily_plan["target_weight"]))
            max_hold.update(dict(zip(daily_plan["symbol"], daily_plan["max_hold_days"])))
        for symbol, entered in list(entry_index.items()):
            if day_index - entered >= int(max_hold.get(symbol, 10)):
                active_targets[symbol] = 0.0
                rebalance = True

        open_equity = cash + sum(shares[symbol] * _price(candles[symbol], date, "open") for symbol in symbols)
        desired = {}
        for symbol in symbols:
            if rebalance:
                price = _price(candles[symbol], date, "open")
                desired[symbol] = _round_lot(open_equity * active_targets.get(symbol, 0.0) / price, config.lot_size) if price > 0 else shares[symbol]
            else:
                desired[symbol] = shares[symbol]

        for side in ("sell", "buy"):
            for symbol in symbols:
                delta = desired[symbol] - shares[symbol]
                if (side == "sell" and delta >= 0) or (side == "buy" and delta <= 0):
                    continue
                frame = candles[symbol]
                if date not in frame.index:
                    continue
                index = int(frame.index.get_loc(date))
                blocked = trade_block_reason(frame.reset_index(drop=False), index, side=side)
                if blocked:
                    trade_rows.append(_trade_row(date, symbol, side, 0, 0.0, 0.0, blocked))
                    continue
                open_price = float(frame.loc[date, "open"])
                if side == "sell":
                    quantity = min(shares[symbol], -delta)
                    fill = open_price * (1 - config.slippage_bps / 10_000)
                    value = quantity * fill
                    fees = max(config.min_commission, value * config.sell_commission_rate) + value * (
                        config.stamp_tax_rate + config.transfer_fee_rate
                    )
                    cash += value - fees
                    shares[symbol] -= quantity
                    if shares[symbol] == 0:
                        entry_index.pop(symbol, None)
                else:
                    fill = open_price * (1 + config.slippage_bps / 10_000)
                    quantity = _affordable_quantity(delta, cash, fill, config)
                    value = quantity * fill
                    fees = max(config.min_commission, value * config.buy_commission_rate) + value * config.transfer_fee_rate if quantity else 0.0
                    cash -= value + fees
                    shares[symbol] += quantity
                    if quantity and symbol not in entry_index:
                        entry_index[symbol] = day_index
                if quantity:
                    trade_rows.append(_trade_row(date, symbol, side, quantity, fill, fees, ""))

        equity = cash + sum(shares[symbol] * _price(candles[symbol], date, "close") for symbol in symbols)
        equity_rows.append(
            {
                "date": date,
                "cash": cash,
                "market_value": equity - cash,
                "equity": equity,
                "daily_return": equity / previous_equity - 1 if previous_equity else 0.0,
                "holding_count": sum(quantity > 0 for quantity in shares.values()),
            }
        )
        previous_equity = equity
        for symbol, quantity in shares.items():
            if quantity <= 0:
                continue
            close = _price(candles[symbol], date, "close")
            position_rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "shares": quantity,
                    "close": close,
                    "market_value": quantity * close,
                    "weight": quantity * close / equity if equity else 0.0,
                    "holding_days": day_index - entry_index.get(symbol, day_index) + 1,
                }
            )
    return ShadowPortfolioResult(pd.DataFrame(equity_rows), pd.DataFrame(trade_rows), pd.DataFrame(position_rows))


def _load_plans(root: Path) -> pd.DataFrame:
    frames = []
    for path in sorted(root.glob("plan_date=*/plan.csv")) if root.exists() else []:
        try:
            frame = pd.read_csv(path, dtype={"symbol": str})
        except pd.errors.EmptyDataError:
            continue
        if frame.empty:
            continue
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    output = pd.concat(frames, ignore_index=True)
    output["symbol"] = output["symbol"].astype(str).str.zfill(6)
    output["plan_date"] = pd.to_datetime(output["plan_date"])
    return output


def _load_candles(symbol: str, *, cache_dir: Path | None) -> pd.DataFrame:
    frame = load_daily_cache(symbol, cache_dir=cache_dir).copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    return frame.sort_values("timestamp").drop_duplicates("timestamp").set_index("timestamp")


def _price(frame: pd.DataFrame, date: pd.Timestamp, column: str) -> float:
    if date not in frame.index:
        return 0.0
    return float(frame.loc[date, column])


def _round_lot(quantity: float, lot_size: int) -> int:
    lot = max(1, int(lot_size))
    return max(0, int(quantity // lot) * lot)


def _affordable_quantity(desired: int, cash: float, fill: float, config: BacktestConfig) -> int:
    quantity = _round_lot(desired, config.lot_size)
    while quantity > 0:
        value = quantity * fill
        fees = max(config.min_commission, value * config.buy_commission_rate) + value * config.transfer_fee_rate
        if value + fees <= cash:
            return quantity
        quantity -= config.lot_size
    return 0


def _trade_row(date: pd.Timestamp, symbol: str, side: str, quantity: int, fill: float, fees: float, blocked: str) -> dict:
    return {
        "date": date,
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "fill_price": fill,
        "fees": fees,
        "blocked_reason": blocked,
    }


def _max_hold_days(value: object) -> int:
    text = str(value or "")
    numbers = [int(part) for part in text.replace("d", "").split("-") if part.isdigit()]
    return max(numbers) if numbers else 10
