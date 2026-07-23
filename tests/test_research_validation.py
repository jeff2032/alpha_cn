from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant_a_stock.backtest.research_portfolio import ResearchPortfolioConfig
from quant_a_stock.backtest.shadow import evaluate_shadow_portfolio
from quant_a_stock.backtest.shadow import freeze_shadow_plan
from quant_a_stock.backtest.shadow import market_position_cap
from quant_a_stock.backtest.shadow import save_shadow_plan
from quant_a_stock.backtest.walk_forward import run_walk_forward_validation
from quant_a_stock.data.cache import save_daily_cache
from quant_a_stock.research.factor_evidence import analyze_factor_evidence
from quant_a_stock.research.fundamental_verdict import merge_fundamental_verdicts
from quant_a_stock.research.fundamental_verdict import normalize_fundamental_verdicts


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
    assert not result.summary["eligible_for_weighting"].any()
    assert set(result.summary["weighting_status"]) == {"样本积累中"}
    assert set(result.quantiles["quantile"]) == {1, 2, 3, 4, 5}
    assert "震荡" in set(result.regimes["market_regime"])


def test_shadow_plan_freezes_caps_and_replays_open_fills(tmp_path: Path) -> None:
    signals = pd.DataFrame(
        [
            {
                "symbol": f"00000{index + 1}",
                "name": f"样本{index + 1}",
                "signal_type": "watch" if tier == "A1" else "buy_watch",
                "action_bucket": {
                    "A1": "观察-A1低位潜伏",
                    "A2": "主攻-A2启动确认",
                    "A3": "短线-A3一三日确认",
                }[tier],
                "research_tier": tier,
                "expected_horizon": {"A1": "10-20d", "A2": "3-5d", "A3": "1-3d"}[tier],
                "research_score": 80 - index,
                "risk_level": "低",
                "theme_cluster": f"主题{index}",
            }
            for index, tier in enumerate(["A2", "A2", "A1", "A1", "A3"])
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
    assert plan["research_tier"].value_counts().to_dict() == {"A2": 2, "A1": 2, "A3": 1}
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


def test_shadow_plan_applies_market_position_gate() -> None:
    signals = pd.DataFrame(
        [
            {
                "symbol": f"0000{index}",
                "name": f"样本{index}",
                "signal_type": "buy_watch",
                "action_bucket": "主攻-A2启动确认",
                "research_tier": "A2",
                "research_score": 80 - index,
                "risk_level": "低",
                "theme_cluster": f"主题{index}",
            }
            for index in range(1, 7)
        ]
    )

    plan = freeze_shadow_plan(
        signals,
        target_date="2026-07-10",
        plan_date="2026-07-13",
        top=5,
        market_regime="防守",
        market_score=30,
    )

    assert len(plan) == 2
    assert plan["target_weight"].sum() == pytest.approx(0.04)
    assert set(plan["market_total_cap"]) == {0.10}
    assert market_position_cap("震荡偏强") == 0.40
    assert market_position_cap("防守", market_score=20) == 0.0


def test_fundamental_verdict_normalizes_and_filters_shadow_plan() -> None:
    raw = pd.DataFrame(
        [
            {"股票代码": "000001.SZ", "基本面结论": "通过", "质量分": "82", "估值风险": "低"},
            {"股票代码": "000002", "基本面结论": "否决", "质量分": "35", "估值风险": "高"},
        ]
    )
    verdicts = normalize_fundamental_verdicts(raw, target_date="2026-07-10")
    signals = pd.DataFrame(
        [
            {"symbol": "000003", "name": "未深研", "signal_type": "buy_watch", "action_bucket": "主攻-A2启动确认", "research_tier": "A2", "research_score": 99, "risk_level": "低"},
            {"symbol": "000001", "name": "已通过", "signal_type": "buy_watch", "action_bucket": "主攻-A2启动确认", "research_tier": "A2", "research_score": 80, "risk_level": "低"},
            {"symbol": "000002", "name": "已否决", "signal_type": "buy_watch", "action_bucket": "主攻-A2启动确认", "research_tier": "A2", "research_score": 90, "risk_level": "低"},
        ]
    )

    plan = freeze_shadow_plan(
        merge_fundamental_verdicts(signals, verdicts),
        target_date="2026-07-10",
        plan_date="2026-07-13",
        top=1,
    )

    assert plan.iloc[0]["symbol"] == "000001"
    assert plan.iloc[0]["fundamental_verdict"] == "pass"
    assert "000002" not in set(plan["symbol"])


def test_stateful_shadow_avoids_daily_rank_churn(tmp_path: Path) -> None:
    plans_root = tmp_path / "plans"
    cache_root = tmp_path / "cache"
    common = {
        "target_date": "2026-01-05",
        "signal_type": "buy_watch",
        "action_bucket": "主攻-A2启动确认",
        "expected_horizon": "3-15d",
        "max_hold_days": 15,
        "industry": "电子",
        "research_score": 80,
        "risk_level": "低",
        "market_regime": "强势",
        "market_score": 80,
        "market_total_cap": 0.8,
    }
    for plan_date, symbols in (("2026-01-06", ["000001", "000002"]), ("2026-01-07", ["000001", "000003"])):
        rows = [{**common, "plan_date": plan_date, "symbol": symbol, "name": symbol, "target_weight": 0.2} for symbol in symbols]
        save_shadow_plan(pd.DataFrame(rows), plan_date=plan_date, root=plans_root)
    for symbol in ("000001", "000002", "000003"):
        save_daily_cache(_candles(symbol, 0.0, days=5), symbol, cache_dir=cache_root)
    for path in (cache_root / "akshare" / "daily").glob("*.csv"):
        frame = pd.read_csv(path)
        frame["timestamp"] = pd.bdate_range("2026-01-06", periods=len(frame)).astype(str)
        frame.to_csv(path, index=False)

    stateful = evaluate_shadow_portfolio(
        plans_root=plans_root,
        cache_dir=cache_root,
        until="2026-01-08",
        mode="stateful",
        max_positions=2,
    )
    daily_target = evaluate_shadow_portfolio(
        plans_root=plans_root,
        cache_dir=cache_root,
        until="2026-01-08",
        mode="daily_target",
    )

    stateful_trades = int((stateful.trades["quantity"] > 0).sum())
    daily_target_trades = int((daily_target.trades["quantity"] > 0).sum())
    assert stateful_trades == 2
    assert daily_target_trades > stateful_trades
    assert set(stateful.positions.loc[stateful.positions["date"] == pd.Timestamp("2026-01-07"), "symbol"]) == {
        "000001",
        "000002",
    }
