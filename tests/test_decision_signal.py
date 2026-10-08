from __future__ import annotations

import pandas as pd

from quant_a_stock.research.decision_signal import DECISION_SIGNAL_VERSION
from quant_a_stock.research.decision_signal import build_decision_signals


def test_build_decision_signals_maps_core_and_watch_buckets() -> None:
    candidates = pd.DataFrame(
        [
            {
                "symbol": "2137",
                "name": "实益达",
                "research_tier": "A2",
                "action_bucket": "主攻-A2启动确认",
                "research_score": 72.0,
                "risk_level": "低",
                "total_penalty": 0,
                "matched_theme": "半导体",
                "top_keywords": "半导体概念、存储芯片",
                "industry": "计算机、通信和其他电子设备制造业",
                "stage": "near_breakout",
                "setup_phase": "接近突破确认",
                "core_news_count": 1,
            },
            {
                "symbol": "600999",
                "name": "招商证券",
                "research_tier": "B2",
                "action_bucket": "升级-B2三五日观察",
                "research_score": 56.0,
                "risk_level": "中",
                "total_penalty": 0,
                "matched_theme": "证券",
                "stage": "accumulation",
            },
            {
                "symbol": "300000",
                "name": "风险样本",
                "research_tier": "C",
                "action_bucket": "回避-风险优先",
                "research_score": 40.0,
                "risk_level": "高",
                "risk_tags": "公告风险",
            },
            {
                "symbol": "600000",
                "name": "低位潜伏",
                "research_tier": "A1",
                "action_bucket": "观察-A1低位潜伏",
                "research_score": 65.0,
                "risk_level": "低",
            },
        ]
    )

    signals = build_decision_signals(candidates, target_date="2026-07-08", plan_date="2026-07-09")

    indexed = signals.set_index("symbol")
    assert indexed.loc["002137", "signal_type"] == "buy_watch"
    assert indexed.loc["002137", "confidence"] == "high"
    assert indexed.loc["002137", "expected_horizon"] == "1-5d"
    assert indexed.loc["002137", "research_horizon"] == "1-10d"
    assert indexed.loc["002137", "max_hold_days"] == 5
    assert indexed.loc["002137", "industry"] == "计算机、通信和其他电子设备制造业"
    assert indexed.loc["002137", "top_keywords"] == "半导体概念、存储芯片"
    assert indexed.loc["600999", "signal_type"] == "upgrade_watch"
    assert indexed.loc["600999", "expected_horizon"] == "1-3d"
    assert indexed.loc["600999", "max_hold_days"] == 0
    assert indexed.loc["300000", "signal_type"] == "avoid"
    assert indexed.loc["300000", "decision_signal_version"] == DECISION_SIGNAL_VERSION
    assert indexed.loc["600000", "expected_horizon"] == "10-20d"
    assert indexed.loc["600000", "research_horizon"] == "10-60d"
    assert indexed.loc["600000", "tracking_window_days"] == 60
    assert indexed.loc["600000", "revalidation_interval_days"] == 5
    assert bool(indexed.loc["600000", "deep_research_eligible"]) is True


def test_high_volatility_a3_is_observation_only() -> None:
    candidates = pd.DataFrame(
        [
            {
                "symbol": "300001",
                "name": "高波动样本",
                "research_tier": "A3",
                "action_bucket": "短线-A3一三日确认",
                "research_score": 70,
                "risk_level": "低",
            },
            {
                "symbol": "300002",
                "name": "趋势延续样本",
                "research_tier": "A3",
                "action_bucket": "主攻-A3趋势延续",
                "research_score": 70,
                "risk_level": "低",
            },
        ]
    )

    signals = build_decision_signals(candidates, target_date="2026-07-31", plan_date="2026-08-03")
    indexed = signals.set_index("symbol")

    assert indexed.loc["300001", "signal_type"] == "hold_watch"
    assert indexed.loc["300001", "decision_bucket"] == "高波动观察"
    assert indexed.loc["300002", "signal_type"] == "buy_watch"
