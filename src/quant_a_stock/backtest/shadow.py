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
    "fundamental_verdict",
    "quality_score",
    "valuation_risk",
    "financial_risk_tags",
    "fundamental_reason_summary",
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


def summarize_shadow_result(
    result: ShadowPortfolioResult,
    *,
    mode: str,
    initial_cash: float,
) -> dict[str, float | int | str]:
    if result.equity.empty:
        return {
            "mode": mode,
            "return_pct": 0.0,
            "max_drawdown": 0.0,
            "trades": 0,
            "fees": 0.0,
            "blocked_trades": 0,
            "avg_holding_count": 0.0,
        }
    equity = pd.to_numeric(result.equity["equity"], errors="coerce").dropna()
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    trades = result.trades.copy()
    quantities = pd.to_numeric(trades.get("quantity", pd.Series(dtype=float)), errors="coerce").fillna(0)
    blocked = trades.get("blocked_reason", pd.Series(dtype=str)).fillna("").astype(str)
    return {
        "mode": mode,
        "return_pct": round(float(equity.iloc[-1] / initial_cash - 1.0), 6),
        "max_drawdown": round(float(drawdown.min()), 6),
        "trades": int((quantities > 0).sum()),
        "fees": round(float(pd.to_numeric(trades.get("fees", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()), 2),
        "blocked_trades": int((blocked != "").sum()),
        "avg_holding_count": round(
            float(pd.to_numeric(result.equity["holding_count"], errors="coerce").fillna(0).mean()), 2
        ),
    }


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
    if "fundamental_verdict" not in frame.columns:
        frame["fundamental_verdict"] = ""
    frame["fundamental_verdict"] = frame["fundamental_verdict"].fillna("").astype(str).str.lower()
    frame = frame[frame["fundamental_verdict"] != "reject"]
    priority = {"buy_watch": 1, "upgrade_watch": 2}
    frame["_priority"] = frame["signal_type"].map(priority).fillna(9)
    verdict_priority = {"pass": 1, "watch": 2, "": 3}
    frame["_fundamental_priority"] = frame["fundamental_verdict"].map(verdict_priority).fillna(3)
    frame = frame[frame["_priority"] < 9].sort_values(
        ["_priority", "_fundamental_priority", "research_score"],
        ascending=[True, True, False],
    )

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
                "fundamental_verdict": row.get("fundamental_verdict", ""),
                "quality_score": row.get("quality_score", ""),
                "valuation_risk": row.get("valuation_risk", ""),
                "financial_risk_tags": row.get("financial_risk_tags", ""),
                "fundamental_reason_summary": row.get("reason_summary", ""),
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
    mode: str = "stateful",
    max_positions: int = 10,
    cooldown_days: int = 3,
    rebalance_tolerance: float = 0.02,
) -> ShadowPortfolioResult:
    if mode not in {"stateful", "daily_target"}:
        raise ValueError(f"Unsupported shadow evaluation mode: {mode}")
    root = plans_root or DEFAULT_PATHS.root / "data" / "shadow" / "plans"
    plans = _load_plans(root)
    if since and not plans.empty:
        plans = plans[plans["plan_date"] >= pd.Timestamp(since)].copy()
    if until and not plans.empty:
        plans = plans[plans["plan_date"] <= pd.Timestamp(until)].copy()
    if plans.empty:
        return ShadowPortfolioResult(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    plan_dates = _load_plan_dates(root, since=since, until=until)
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
    min_hold = {
        str(row["symbol"]): _min_hold_days(row.get("expected_horizon", ""))
        for _, row in plans.iterrows()
    }
    last_exit_index: dict[str, int] = {}
    active_targets: dict[str, float] = {}
    current_market_cap = 0.0
    equity_rows = []
    trade_rows = []
    position_rows = []
    previous_equity = cash

    for day_index, date in enumerate(all_dates):
        daily_plan = plan_by_date.get(date)
        open_equity = cash + sum(shares[symbol] * _price(candles[symbol], date, "open") for symbol in symbols)
        trade_reasons: dict[str, str] = {}
        if mode == "daily_target":
            desired, active_targets = _daily_target_desired(
                date=date,
                day_index=day_index,
                is_plan_day=date in plan_dates,
                daily_plan=daily_plan,
                symbols=symbols,
                shares=shares,
                entry_index=entry_index,
                max_hold=max_hold,
                active_targets=active_targets,
                candles=candles,
                open_equity=open_equity,
                config=config,
            )
            trade_reasons = {symbol: "daily_target_rebalance" for symbol in symbols if desired[symbol] != shares[symbol]}
        else:
            desired, current_market_cap, state_reasons = _stateful_desired(
                date=date,
                day_index=day_index,
                is_plan_day=date in plan_dates,
                daily_plan=daily_plan,
                symbols=symbols,
                shares=shares,
                entry_index=entry_index,
                last_exit_index=last_exit_index,
                min_hold=min_hold,
                max_hold=max_hold,
                candles=candles,
                open_equity=open_equity,
                current_market_cap=current_market_cap,
                max_positions=max_positions,
                cooldown_days=cooldown_days,
                rebalance_tolerance=rebalance_tolerance,
                config=config,
            )
            trade_reasons.update(state_reasons)

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
                    trade_rows.append(
                        _trade_row(date, symbol, side, 0, 0.0, 0.0, blocked, trade_reasons.get(symbol, ""))
                    )
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
                        last_exit_index[symbol] = day_index
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
                    trade_rows.append(
                        _trade_row(date, symbol, side, quantity, fill, fees, "", trade_reasons.get(symbol, ""))
                    )

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


def _load_plan_dates(root: Path, *, since: str | None, until: str | None) -> set[pd.Timestamp]:
    dates: set[pd.Timestamp] = set()
    for directory in sorted(root.glob("plan_date=*")) if root.exists() else []:
        try:
            date = pd.Timestamp(directory.name.split("=", 1)[1]).normalize()
        except (IndexError, ValueError):
            continue
        if since and date < pd.Timestamp(since):
            continue
        if until and date > pd.Timestamp(until):
            continue
        dates.add(date)
    return dates


def _daily_target_desired(
    *,
    date: pd.Timestamp,
    day_index: int,
    is_plan_day: bool,
    daily_plan: pd.DataFrame | None,
    symbols: list[str],
    shares: dict[str, int],
    entry_index: dict[str, int],
    max_hold: dict[str, int],
    active_targets: dict[str, float],
    candles: dict[str, pd.DataFrame],
    open_equity: float,
    config: BacktestConfig,
) -> tuple[dict[str, int], dict[str, float]]:
    rebalance = is_plan_day
    if rebalance:
        active_targets = (
            dict(zip(daily_plan["symbol"], daily_plan["target_weight"]))
            if daily_plan is not None
            else {}
        )
        if daily_plan is not None:
            max_hold.update(dict(zip(daily_plan["symbol"], daily_plan["max_hold_days"])))
    for symbol, entered in list(entry_index.items()):
        if day_index - entered >= int(max_hold.get(symbol, 10)):
            active_targets[symbol] = 0.0
            rebalance = True
    desired = {}
    for symbol in symbols:
        if not rebalance:
            desired[symbol] = shares[symbol]
            continue
        price = _price(candles[symbol], date, "open")
        desired[symbol] = (
            _round_lot(open_equity * active_targets.get(symbol, 0.0) / price, config.lot_size)
            if price > 0
            else shares[symbol]
        )
    return desired, active_targets


def _stateful_desired(
    *,
    date: pd.Timestamp,
    day_index: int,
    is_plan_day: bool,
    daily_plan: pd.DataFrame | None,
    symbols: list[str],
    shares: dict[str, int],
    entry_index: dict[str, int],
    last_exit_index: dict[str, int],
    min_hold: dict[str, int],
    max_hold: dict[str, int],
    candles: dict[str, pd.DataFrame],
    open_equity: float,
    current_market_cap: float,
    max_positions: int,
    cooldown_days: int,
    rebalance_tolerance: float,
    config: BacktestConfig,
) -> tuple[dict[str, int], float, dict[str, str]]:
    desired = dict(shares)
    reasons: dict[str, str] = {}

    if daily_plan is not None and not daily_plan.empty:
        for _, row in daily_plan.iterrows():
            symbol = str(row["symbol"]).zfill(6)
            min_hold[symbol] = _min_hold_days(row.get("expected_horizon", ""))
            max_hold[symbol] = int(row.get("max_hold_days", _max_hold_days(row.get("expected_horizon", ""))))
        if "market_total_cap" in daily_plan.columns:
            parsed_cap = pd.to_numeric(daily_plan["market_total_cap"], errors="coerce").dropna()
            if not parsed_cap.empty:
                current_market_cap = float(parsed_cap.iloc[0])

    if is_plan_day and (daily_plan is None or daily_plan.empty):
        current_market_cap = 0.0
        for symbol, quantity in shares.items():
            if quantity > 0:
                desired[symbol] = 0
                reasons[symbol] = "all_cash_plan"
        return desired, current_market_cap, reasons

    for symbol, entered in list(entry_index.items()):
        if day_index - entered >= int(max_hold.get(symbol, 10)):
            desired[symbol] = 0
            reasons[symbol] = "max_holding_period"

    if daily_plan is not None and not daily_plan.empty:
        plan_symbols = set(daily_plan["symbol"].astype(str).str.zfill(6))
        for symbol, entered in list(entry_index.items()):
            holding_days = day_index - entered
            if symbol not in plan_symbols and holding_days >= int(min_hold.get(symbol, 1)):
                desired[symbol] = 0
                reasons[symbol] = "not_reselected_after_min_hold"

        projected_count = sum(quantity > 0 for quantity in desired.values())
        slots = max(0, int(max_positions) - projected_count)
        for _, row in daily_plan.iterrows():
            if slots <= 0:
                break
            symbol = str(row["symbol"]).zfill(6)
            if desired.get(symbol, 0) > 0:
                continue
            last_exit = last_exit_index.get(symbol)
            if last_exit is not None and day_index - last_exit < max(0, int(cooldown_days)):
                continue
            price = _price(candles[symbol], date, "open")
            if price <= 0:
                continue
            target_weight = float(pd.to_numeric(pd.Series([row.get("target_weight", 0.0)]), errors="coerce").fillna(0.0).iloc[0])
            quantity = _round_lot(open_equity * target_weight / price, config.lot_size)
            if quantity <= 0:
                continue
            desired[symbol] = quantity
            reasons[symbol] = "new_plan_entry"
            slots -= 1

    desired_value = sum(
        quantity * _price(candles[symbol], date, "open")
        for symbol, quantity in desired.items()
        if quantity > 0
    )
    cap_value = max(0.0, current_market_cap) * open_equity
    tolerance_value = max(0.0, float(rebalance_tolerance)) * open_equity
    if desired_value > cap_value + tolerance_value and desired_value > 0:
        scale = cap_value / desired_value if cap_value > 0 else 0.0
        for symbol, quantity in list(desired.items()):
            if quantity <= 0:
                continue
            reduced = _round_lot(quantity * scale, config.lot_size)
            if reduced < quantity:
                desired[symbol] = reduced
                reasons[symbol] = "market_cap_deleveraging"
    return desired, current_market_cap, reasons


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


def _trade_row(
    date: pd.Timestamp,
    symbol: str,
    side: str,
    quantity: int,
    fill: float,
    fees: float,
    blocked: str,
    reason: str = "",
) -> dict:
    return {
        "date": date,
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "fill_price": fill,
        "fees": fees,
        "blocked_reason": blocked,
        "trade_reason": reason,
    }


def _max_hold_days(value: object) -> int:
    text = str(value or "")
    numbers = [int(part) for part in text.replace("d", "").split("-") if part.isdigit()]
    return max(numbers) if numbers else 10


def _min_hold_days(value: object) -> int:
    text = str(value or "")
    numbers = [int(part) for part in text.replace("d", "").split("-") if part.isdigit()]
    return min(numbers) if numbers else 1
