from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quant_a_stock.backtest.research_portfolio import ResearchPortfolioConfig
from quant_a_stock.backtest.research_portfolio import run_research_portfolio_backtest_from_factors
from quant_a_stock.config import BacktestConfig, DEFAULT_BACKTEST_CONFIG


@dataclass(frozen=True)
class WalkForwardResult:
    folds: pd.DataFrame
    aggregate: pd.DataFrame


def run_walk_forward_validation(
    candles_by_symbol: dict[str, pd.DataFrame],
    factors: pd.DataFrame,
    *,
    candidate_configs: list[ResearchPortfolioConfig],
    train_days: int = 252,
    test_days: int = 63,
    step_days: int | None = None,
    embargo_days: int = 5,
    backtest_config: BacktestConfig = DEFAULT_BACKTEST_CONFIG,
) -> WalkForwardResult:
    if factors.empty or not candidate_configs:
        return WalkForwardResult(pd.DataFrame(), pd.DataFrame())
    dates = pd.Series(pd.to_datetime(factors["timestamp"]).drop_duplicates().sort_values().tolist())
    step = step_days or test_days
    rows = []
    fold = 1
    cursor = train_days + embargo_days
    while cursor + test_days <= len(dates):
        train_start = dates.iloc[cursor - embargo_days - train_days]
        train_end = dates.iloc[cursor - embargo_days - 1]
        test_start = dates.iloc[cursor]
        test_end = dates.iloc[cursor + test_days - 1]

        scored = []
        for config in candidate_configs:
            train = run_research_portfolio_backtest_from_factors(
                candles_by_symbol,
                factors,
                since=train_start.date().isoformat(),
                until=train_end.date().isoformat(),
                portfolio_config=config,
                backtest_config=backtest_config,
            )
            scored.append((float(train.metrics.get("sharpe", 0.0)), float(train.metrics.get("return_pct", 0.0)), config))
        _, _, best = max(scored, key=lambda item: (item[0], item[1]))
        test = run_research_portfolio_backtest_from_factors(
            candles_by_symbol,
            factors,
            since=test_start.date().isoformat(),
            until=test_end.date().isoformat(),
            portfolio_config=best,
            backtest_config=backtest_config,
        )
        best_train = max(scored, key=lambda item: (item[0], item[1]))
        rows.append(
            {
                "fold": fold,
                "train_start": train_start.date().isoformat(),
                "train_end": train_end.date().isoformat(),
                "test_start": test_start.date().isoformat(),
                "test_end": test_end.date().isoformat(),
                "embargo_days": embargo_days,
                "top_n": best.top_n,
                "min_score": best.min_score,
                "max_ret_20": best.max_ret_20,
                "rebalance_frequency": best.rebalance_frequency,
                "train_sharpe": best_train[0],
                "train_return_pct": best_train[1],
                "oos_return_pct": test.metrics.get("return_pct", 0.0),
                "oos_sharpe": test.metrics.get("sharpe", 0.0),
                "oos_max_drawdown": test.metrics.get("max_drawdown", 0.0),
                "oos_trades": test.metrics.get("trades", 0),
                "oos_exposure_pct": test.metrics.get("exposure_pct", 0.0),
            }
        )
        fold += 1
        cursor += step

    folds = pd.DataFrame(rows)
    if folds.empty:
        return WalkForwardResult(folds, pd.DataFrame())
    aggregate = pd.DataFrame(
        [
            {
                "folds": len(folds),
                "positive_folds": int((folds["oos_return_pct"] > 0).sum()),
                "positive_fold_rate": float((folds["oos_return_pct"] > 0).mean()),
                "avg_oos_return_pct": float(folds["oos_return_pct"].mean()),
                "median_oos_return_pct": float(folds["oos_return_pct"].median()),
                "avg_oos_sharpe": float(folds["oos_sharpe"].mean()),
                "worst_oos_drawdown": float(folds["oos_max_drawdown"].min()),
                "parameter_stability": float(
                    folds[["top_n", "min_score", "max_ret_20", "rebalance_frequency"]]
                    .value_counts(normalize=True)
                    .max()
                ),
            }
        ]
    )
    return WalkForwardResult(folds, aggregate)
