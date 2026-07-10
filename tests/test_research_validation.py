from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from quant_a_stock.backtest.research_portfolio import ResearchPortfolioConfig
from quant_a_stock.backtest.shadow import evaluate_shadow_portfolio
from quant_a_stock.backtest.shadow import freeze_shadow_plan
from quant_a_stock.backtest.shadow import save_shadow_plan
from quant_a_stock.backtest.walk_forward import run_walk_forward_validation
from quant_a_stock.data.cache import save_daily_cache
from quant_a_stock.research.factor_evidence import analyze_factor_evidence


def _candles(symbol: str, drift: float, days: int = 140) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=days)
    close = pd.Series([10 + index * drift for index in range(days)])
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000_000,
            "amount": close * 1_000_000,
            "symbol": symbol,
        }
    )


def test_walk_forward_uses_separate_train_and_oos_windows() -> None:
    candles = {"000001": _candles("000001", 0.02), "000002": _candles("000002", 0.01)}
    dates = pd.bdate_range("2025-01-02", periods=140)
    factors = pd.DataFrame(
        [
            {
                "timestamp": date,
                "symbol": symbol,
                "stage": "watch",
                "score": 60 + (symbol == "000001"),
                "volume_ratio": 1.2,
                "amount_ma20": 1_000_000_000,
                "close_vs_trend_pct": 0.1,
                "ret_20_pct": 0.1,
                "trend_slope_20_pct": 0.1,
            }
            for date in dates
            for symbol in candles
        ]
    )
    configs = [
        ResearchPortfolioConfig(top_n=1, min_score=0, min_amount_ma20=1, max_close_vs_trend=1, max_ret_20=1),
        ResearchPortfolioConfig(top_n=2, min_score=0, min_amount_ma20=1, max_close_vs_trend=1, max_ret_20=1),
    ]

    result = run_walk_forward_validation(
        candles,
        factors,
        candidate_configs=configs,
        train_days=60,
        test_days=20,
        step_days=20,
        embargo_days=5,
    )

    assert len(result.folds) >= 3
    assert (pd.to_datetime(result.folds["train_end"]) < pd.to_datetime(result.folds["test_start"])).all()
    assert result.aggregate.loc[0, "folds"] == len(result.folds)


def test_factor_evidence_calculates_ic_quantiles_and_regimes() -> None:
    rows = []
    for day in pd.bdate_range("2026-01-02", periods=6):
        for rank in range(1, 11):
            rows.append(
                {
                    "signal_date": day,
                    "symbol": f"{rank:06d}",
                    "price_position_pct": rank / 10,
                    "volume_ratio": rank,
                    "ret_20_pct": rank / 100,
                    "ret_60_pct": rank / 50,
                    "mtf_score": rank,
                    "co_rise_count": rank,
                    "total_penalty": 11 - rank,
                    "risk_event_score": 11 - rank,
                    "benchmark_ret_5d": 0.01,
                    "excess_ret_5d": rank / 100,
                }
            )

    result = analyze_factor_evidence(pd.DataFrame(rows), horizon="5d", quantile_count=5)

    assert not result.summary.empty
    assert "mean_ic" in result.summary.columns
    assert set(result.quantiles["quantile"]) == {1, 2, 3, 4, 5}
    assert "震荡" in set(result.regimes["market_regime"])


def test_shadow_plan_freezes_caps_and_replays_open_fills(tmp_path: Path) -> None:
    signals = pd.DataFrame(
        [
            {
                "symbol": f"00000{index}",
                "name": f"样本{index}",
                "signal_type": "buy_watch",
                "action_bucket": "主攻-A2启动确认",
                "expected_horizon": "3-15d",
                "research_score": 80 - index,
                "risk_level": "低",
                "theme_cluster": "电子" if index <= 3 else "化工",
            }
            for index in range(1, 6)
        ]
    )
    plan = freeze_shadow_plan(signals, target_date="2026-01-05", plan_date="2026-01-06", top=5)
    plans_root = tmp_path / "plans"
    save_shadow_plan(plan, plan_date="2026-01-06", root=plans_root)
    cache_root = tmp_path / "cache"
    for symbol in plan["symbol"]:
        save_daily_cache(_candles(symbol, 0.02, days=10), symbol, cache_dir=cache_root)
    # Align the synthetic cache to the frozen plan date.
    for path in (cache_root / "akshare" / "daily").glob("*.csv"):
        frame = pd.read_csv(path)
        frame["timestamp"] = pd.bdate_range("2026-01-06", periods=len(frame)).astype(str)
        frame.to_csv(path, index=False)

    result = evaluate_shadow_portfolio(plans_root=plans_root, cache_dir=cache_root, until="2026-01-12")

    assert plan["target_weight"].sum() <= 0.80 + 1e-9
    assert plan.groupby("industry")["target_weight"].sum().max() <= 0.30 + 1e-9
    assert not result.equity.empty
    assert (result.trades["quantity"] > 0).any()
    assert result.positions["shares"].mod(100).eq(0).all()


def test_empty_shadow_plan_is_a_valid_all_cash_decision(tmp_path: Path) -> None:
    plan = freeze_shadow_plan(pd.DataFrame(), target_date="2026-01-05", plan_date="2026-01-06")
    path = save_shadow_plan(plan, plan_date="2026-01-06", root=tmp_path / "plans")

    assert path.exists()
    assert "symbol" in pd.read_csv(path).columns
    result = evaluate_shadow_portfolio(plans_root=tmp_path / "plans", until="2026-01-06")
    assert result.equity.empty
