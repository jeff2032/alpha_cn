from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from quant_a_stock.backtest.engine import TRADING_DAYS_PER_YEAR
from quant_a_stock.config import BacktestConfig, DEFAULT_BACKTEST_CONFIG
from quant_a_stock.screening.patterns import BaseBreakoutSetupConfig


@dataclass(frozen=True)
class ResearchPortfolioConfig:
    top_n: int = 10
    min_score: float = 50.0
    min_amount_ma20: float = 100_000_000.0
    min_volume_ratio: float | None = None
    max_close_vs_trend: float = 0.25
    max_ret_20: float = 0.25
    require_positive_trend_slope: bool = True
    rebalance_frequency: str = "D"
    allow_stages: tuple[str, ...] = ("watch", "near_breakout")


@dataclass(frozen=True)
class ResearchPortfolioBacktestResult:
    equity_curve: pd.DataFrame
    holdings: pd.DataFrame
    candidates: pd.DataFrame
    metrics: dict[str, float | int | str]
    yearly: pd.DataFrame


def run_research_portfolio_backtest(
    candles_by_symbol: dict[str, pd.DataFrame],
    *,
    since: str,
    until: str | None = None,
    setup_config: BaseBreakoutSetupConfig = BaseBreakoutSetupConfig(),
    portfolio_config: ResearchPortfolioConfig = ResearchPortfolioConfig(),
    backtest_config: BacktestConfig = DEFAULT_BACKTEST_CONFIG,
) -> ResearchPortfolioBacktestResult:
    factors = build_research_factor_panel(candles_by_symbol, setup_config=setup_config)
    return run_research_portfolio_backtest_from_factors(
        candles_by_symbol,
        factors,
        since=since,
        until=until,
        portfolio_config=portfolio_config,
        backtest_config=backtest_config,
    )


def build_research_factor_panel(
    candles_by_symbol: dict[str, pd.DataFrame],
    *,
    setup_config: BaseBreakoutSetupConfig = BaseBreakoutSetupConfig(),
) -> pd.DataFrame:
    return _build_factor_panel(candles_by_symbol, setup_config=setup_config)


def run_research_portfolio_backtest_from_factors(
    candles_by_symbol: dict[str, pd.DataFrame],
    factors: pd.DataFrame,
    *,
    since: str,
    until: str | None = None,
    portfolio_config: ResearchPortfolioConfig = ResearchPortfolioConfig(),
    backtest_config: BacktestConfig = DEFAULT_BACKTEST_CONFIG,
    return_panel: pd.DataFrame | None = None,
) -> ResearchPortfolioBacktestResult:
    if factors.empty:
        empty = pd.DataFrame()
        return ResearchPortfolioBacktestResult(
            equity_curve=empty,
            holdings=empty,
            candidates=empty,
            metrics=_empty_metrics(),
            yearly=empty,
        )

    since_ts = pd.Timestamp(since)
    until_ts = pd.Timestamp(until) if until else factors["timestamp"].max()
    factors = factors[
        (factors["timestamp"] >= since_ts) & (factors["timestamp"] <= until_ts)
    ].reset_index(drop=True)
    factors = _filter_candidate_panel(factors, config=portfolio_config)
    if factors.empty:
        empty = pd.DataFrame()
        return ResearchPortfolioBacktestResult(
            equity_curve=empty,
            holdings=empty,
            candidates=empty,
            metrics=_empty_metrics(),
            yearly=empty,
        )

    candidates = factors.sort_values(
        ["timestamp", "score", "volume_ratio"],
        ascending=[True, False, False],
    ).reset_index(drop=True)
    holdings = _select_holdings(candidates, config=portfolio_config)
    if return_panel is None:
        return_panel = _build_return_panel(candles_by_symbol, since=since_ts, until=until_ts)
    equity_curve = _simulate_equal_weight_portfolio_from_return_panel(
        return_panel,
        holdings,
        config=backtest_config,
    )
    metrics = summarize_research_portfolio(equity_curve, holdings, candidates)
    yearly = yearly_research_portfolio_metrics(equity_curve)
    return ResearchPortfolioBacktestResult(
        equity_curve=equity_curve,
        holdings=holdings,
        candidates=candidates,
        metrics=metrics,
        yearly=yearly,
    )


def optimize_research_portfolio(
    candles_by_symbol: dict[str, pd.DataFrame],
    *,
    since: str,
    until: str | None = None,
    top_ns: list[int],
    min_scores: list[float],
    max_ret_20s: list[float],
    rebalance_frequencies: list[str],
    min_amount_ma20: float = 100_000_000.0,
    min_volume_ratio: float | None = None,
    max_close_vs_trend: float = 0.25,
    require_positive_trend_slope: bool = True,
    allow_stages: tuple[str, ...] = ("watch", "near_breakout"),
    setup_config: BaseBreakoutSetupConfig = BaseBreakoutSetupConfig(),
    backtest_config: BacktestConfig = DEFAULT_BACKTEST_CONFIG,
) -> pd.DataFrame:
    factors = build_research_factor_panel(candles_by_symbol, setup_config=setup_config)
    if factors.empty:
        return pd.DataFrame()
    since_ts = pd.Timestamp(since)
    until_ts = pd.Timestamp(until) if until else factors["timestamp"].max()
    return_panel = _build_return_panel(candles_by_symbol, since=since_ts, until=until_ts)
    if return_panel.empty:
        return pd.DataFrame()

    rows = []
    for top_n in top_ns:
        for min_score in min_scores:
            for max_ret_20 in max_ret_20s:
                for frequency in rebalance_frequencies:
                    config = ResearchPortfolioConfig(
                        top_n=top_n,
                        min_score=min_score,
                        min_amount_ma20=min_amount_ma20,
                        min_volume_ratio=min_volume_ratio,
                        max_close_vs_trend=max_close_vs_trend,
                        max_ret_20=max_ret_20,
                        require_positive_trend_slope=require_positive_trend_slope,
                        rebalance_frequency=frequency,
                        allow_stages=allow_stages,
                    )
                    result = run_research_portfolio_backtest_from_factors(
                        candles_by_symbol,
                        factors,
                        since=since,
                        until=until,
                        portfolio_config=config,
                        backtest_config=backtest_config,
                        return_panel=return_panel,
                    )
                    rows.append(
                        {
                            "top_n": top_n,
                            "min_score": min_score,
                            "max_ret_20": max_ret_20,
                            "rebalance_frequency": frequency,
                            **result.metrics,
                        }
                    )

    output = pd.DataFrame(rows)
    if output.empty:
        return output
    output = output.sort_values(
        ["sharpe", "return_pct", "max_drawdown"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    output.insert(0, "rank", range(1, len(output) + 1))
    return output


def summarize_research_portfolio(
    equity_curve: pd.DataFrame,
    holdings: pd.DataFrame,
    candidates: pd.DataFrame,
) -> dict[str, float | int | str]:
    if equity_curve.empty:
        return _empty_metrics()

    total_return = equity_curve["equity"].iloc[-1] / equity_curve["equity"].iloc[0] - 1
    daily_returns = equity_curve["strategy_return"]
    drawdown = equity_curve["equity"] / equity_curve["equity"].cummax() - 1
    std = daily_returns.std(ddof=0)
    sharpe = 0.0 if std == 0 or np.isnan(std) else daily_returns.mean() / std * np.sqrt(TRADING_DAYS_PER_YEAR)

    return {
        "symbol": "RESEARCH_PORTFOLIO",
        "return_pct": float(total_return),
        "max_drawdown": float(drawdown.min()),
        "sharpe": float(sharpe),
        "trades": int(equity_curve["buy_count"].sum()),
        "exposure_pct": float((equity_curve["gross_exposure"] > 0).mean()),
        "avg_holdings": float(equity_curve["holding_count"].mean()),
        "avg_turnover": float(equity_curve["turnover"].mean()),
        "candidate_days": int(candidates["timestamp"].nunique()) if not candidates.empty else 0,
        "holding_rows": int(len(holdings)),
    }


def yearly_research_portfolio_metrics(equity_curve: pd.DataFrame) -> pd.DataFrame:
    if equity_curve.empty:
        return pd.DataFrame()

    rows = []
    for year, frame in equity_curve.groupby(equity_curve["timestamp"].dt.year):
        yearly = frame.copy()
        yearly["equity"] = (1 + yearly["strategy_return"]).cumprod()
        drawdown = yearly["equity"] / yearly["equity"].cummax() - 1
        std = yearly["strategy_return"].std(ddof=0)
        sharpe = 0.0 if std == 0 or np.isnan(std) else yearly["strategy_return"].mean() / std * np.sqrt(TRADING_DAYS_PER_YEAR)
        rows.append(
            {
                "year": int(year),
                "symbol": "RESEARCH_PORTFOLIO",
                "return_pct": float(yearly["equity"].iloc[-1] / yearly["equity"].iloc[0] - 1),
                "max_drawdown": float(drawdown.min()),
                "sharpe": float(sharpe),
                "trades": int(yearly["buy_count"].sum()),
                "exposure_pct": float((yearly["gross_exposure"] > 0).mean()),
                "avg_holdings": float(yearly["holding_count"].mean()),
                "avg_turnover": float(yearly["turnover"].mean()),
            }
        )
    return pd.DataFrame(rows)


def _build_factor_panel(
    candles_by_symbol: dict[str, pd.DataFrame],
    *,
    setup_config: BaseBreakoutSetupConfig,
) -> pd.DataFrame:
    rows = []
    for symbol, candles in candles_by_symbol.items():
        factor = _symbol_factor_frame(candles, symbol=symbol, config=setup_config)
        if not factor.empty:
            rows.append(factor)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def _symbol_factor_frame(
    candles: pd.DataFrame,
    *,
    symbol: str,
    config: BaseBreakoutSetupConfig,
) -> pd.DataFrame:
    if candles.empty:
        return pd.DataFrame()
    frame = candles.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    required_bars = max(config.base_window, config.trend_window, config.volume_window, 60) + 21
    if len(frame) < required_bars:
        return pd.DataFrame()

    close = frame["close"]
    volume = frame["volume"]
    amount = frame["amount"] if "amount" in frame.columns else close * volume

    prior_high = close.shift(1).rolling(config.base_window, min_periods=config.base_window).max()
    prior_low = close.shift(1).rolling(config.base_window, min_periods=config.base_window).min()
    base_range = prior_high / prior_low - 1
    trend_ma = close.rolling(config.trend_window, min_periods=config.trend_window).mean()
    trend_slope_20 = trend_ma / trend_ma.shift(20) - 1
    volume_ratio = volume / volume.rolling(config.volume_window, min_periods=config.volume_window).mean()
    amount_ma20 = amount.rolling(config.volume_window, min_periods=config.volume_window).mean()
    ret_20 = close / close.shift(20) - 1
    ret_60 = close / close.shift(60) - 1
    distance_to_high = close / prior_high - 1
    close_vs_trend = close / trend_ma - 1

    base_score = _clip_series((config.max_base_range - base_range) / 0.45 * 25, high=25)
    proximity_score = _proximity_score_series(distance_to_high, config.proximity_pct)
    trend_score = _clip_series((close_vs_trend + 0.02) / 0.16 * 20, high=20)
    slope_score = _clip_series((trend_slope_20 + 0.01) / 0.08 * 15, high=15)
    volume_score = _clip_series((volume_ratio - 1.0) / 2.0 * 20, high=20)
    overheat_penalty = (
        _clip_series((ret_20 - config.max_ret_20) / 0.25 * 60, high=60)
        + _clip_series((close_vs_trend - 0.50) / 1.0 * 30, high=30)
        + _clip_series((base_range - config.max_base_range) / 1.0 * 20, high=20)
    )
    score = (base_score + proximity_score + trend_score + slope_score + volume_score - overheat_penalty).clip(0, 100)

    stage = pd.Series("watch", index=frame.index, dtype=object)
    stage = stage.mask(close > prior_high, "breakout")
    stage = stage.mask((close <= prior_high) & (distance_to_high >= -config.proximity_pct), "near_breakout")
    stage = stage.mask(ret_20 > config.max_ret_20, "extended")

    output = pd.DataFrame(
        {
            "timestamp": frame["timestamp"],
            "symbol": symbol,
            "stage": stage,
            "score": score.round(2),
            "close": close,
            "base_range_pct": base_range,
            "distance_to_high_pct": distance_to_high,
            "close_vs_trend_pct": close_vs_trend,
            "trend_slope_20_pct": trend_slope_20,
            "volume_ratio": volume_ratio,
            "amount_ma20": amount_ma20,
            "ret_20_pct": ret_20,
            "ret_60_pct": ret_60,
        }
    )
    return output.dropna(subset=["score", "amount_ma20", "ret_20_pct", "ret_60_pct"])


def _filter_candidate_panel(
    panel: pd.DataFrame,
    *,
    config: ResearchPortfolioConfig,
) -> pd.DataFrame:
    output = panel.copy()
    output = output[output["stage"].isin(config.allow_stages)]
    output = output[output["score"] >= config.min_score]
    output = output[output["amount_ma20"] >= config.min_amount_ma20]
    output = output[output["close_vs_trend_pct"] <= config.max_close_vs_trend]
    output = output[output["ret_20_pct"] <= config.max_ret_20]
    if config.min_volume_ratio is not None:
        output = output[output["volume_ratio"] >= config.min_volume_ratio]
    if config.require_positive_trend_slope:
        output = output[output["trend_slope_20_pct"] > 0]
    return output.reset_index(drop=True)


def _select_holdings(
    candidates: pd.DataFrame,
    *,
    config: ResearchPortfolioConfig,
) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame(columns=["timestamp", "symbol", "target_weight", "rank", "score"])

    rebalance_dates = _rebalance_dates(candidates["timestamp"].drop_duplicates().sort_values(), config.rebalance_frequency)
    rows = []
    for timestamp, group in candidates[candidates["timestamp"].isin(rebalance_dates)].groupby("timestamp"):
        selected = group.sort_values(["score", "volume_ratio"], ascending=[False, False]).head(config.top_n)
        if selected.empty:
            continue
        weight = 1.0 / len(selected)
        for rank, (_, row) in enumerate(selected.iterrows(), start=1):
            rows.append(
                {
                    "timestamp": timestamp,
                    "symbol": row["symbol"],
                    "target_weight": weight,
                    "rank": rank,
                    "score": row["score"],
                    "stage": row["stage"],
                }
            )
    return pd.DataFrame(rows)


def _rebalance_dates(dates: pd.Series, frequency: str) -> pd.Series:
    if frequency.upper() == "D":
        return dates
    frame = pd.DataFrame({"timestamp": pd.to_datetime(dates)})
    if frequency.upper() == "W":
        return frame.groupby(frame["timestamp"].dt.to_period("W"))["timestamp"].max().reset_index(drop=True)
    if frequency.upper() == "M":
        return frame.groupby(frame["timestamp"].dt.to_period("M"))["timestamp"].max().reset_index(drop=True)
    raise ValueError("rebalance_frequency 只支持 D/W/M")


def _simulate_equal_weight_portfolio(
    candles_by_symbol: dict[str, pd.DataFrame],
    holdings: pd.DataFrame,
    *,
    since: pd.Timestamp,
    until: pd.Timestamp,
    config: BacktestConfig,
) -> pd.DataFrame:
    return_panel = _build_return_panel(candles_by_symbol, since=since, until=until)
    return _simulate_equal_weight_portfolio_from_return_panel(
        return_panel,
        holdings,
        config=config,
    )


def _simulate_equal_weight_portfolio_from_return_panel(
    return_panel: pd.DataFrame,
    holdings: pd.DataFrame,
    *,
    config: BacktestConfig,
) -> pd.DataFrame:
    if holdings.empty or return_panel.empty:
        return pd.DataFrame()

    target_weights = holdings.pivot_table(
        index="timestamp",
        columns="symbol",
        values="target_weight",
        aggfunc="sum",
    )
    target_weights = target_weights.reindex(columns=return_panel.columns, fill_value=0.0)
    target_weights = target_weights.fillna(0.0)
    target_weights = target_weights.reindex(return_panel.index).ffill().fillna(0.0)
    weights = target_weights.shift(1).fillna(0.0) if config.trade_on_next_bar else target_weights

    delta = weights.diff().fillna(weights)
    buy_turnover = delta.clip(lower=0).sum(axis=1)
    sell_turnover = (-delta.clip(upper=0)).sum(axis=1)
    cost = buy_turnover * (config.buy_commission_rate + config.transfer_fee_rate)
    cost += sell_turnover * (
        config.sell_commission_rate + config.stamp_tax_rate + config.transfer_fee_rate
    )

    gross_return = (weights * return_panel.fillna(0.0)).sum(axis=1)
    strategy_return = gross_return - cost
    equity = config.initial_cash * (1 + strategy_return).cumprod()

    return pd.DataFrame(
        {
            "timestamp": return_panel.index,
            "gross_return": gross_return.values,
            "cost": cost.values,
            "strategy_return": strategy_return.values,
            "equity": equity.values,
            "gross_exposure": weights.sum(axis=1).values,
            "holding_count": (weights > 0).sum(axis=1).values,
            "turnover": (buy_turnover + sell_turnover).values,
            "buy_count": (delta > 0).sum(axis=1).values,
            "sell_count": (delta < 0).sum(axis=1).values,
        }
    )


def _build_return_panel(
    candles_by_symbol: dict[str, pd.DataFrame],
    *,
    since: pd.Timestamp,
    until: pd.Timestamp,
) -> pd.DataFrame:
    returns = []
    for symbol, candles in candles_by_symbol.items():
        if candles.empty:
            continue
        frame = candles.copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"])
        frame = frame.sort_values("timestamp")
        series = frame.set_index("timestamp")["close"].pct_change().rename(symbol)
        series = series[(series.index >= since) & (series.index <= until)]
        if not series.empty:
            returns.append(series)
    if not returns:
        return pd.DataFrame()
    return pd.concat(returns, axis=1).sort_index().fillna(0.0)


def _clip_series(series: pd.Series, low: float = 0.0, high: float = 100.0) -> pd.Series:
    return series.replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=low, upper=high)


def _proximity_score_series(distance_to_high: pd.Series, proximity_pct: float) -> pd.Series:
    below_or_equal = ((distance_to_high + proximity_pct) / proximity_pct * 20).clip(upper=20)
    above = 20 - distance_to_high / 0.20 * 20
    score = below_or_equal.where(distance_to_high <= 0, above)
    return _clip_series(score, high=20)


def _empty_metrics() -> dict[str, float | int | str]:
    return {
        "symbol": "RESEARCH_PORTFOLIO",
        "return_pct": 0.0,
        "max_drawdown": 0.0,
        "sharpe": 0.0,
        "trades": 0,
        "exposure_pct": 0.0,
        "avg_holdings": 0.0,
        "avg_turnover": 0.0,
        "candidate_days": 0,
        "holding_rows": 0,
    }
